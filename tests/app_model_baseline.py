"""Deterministic version-1 workspaces and a normalized capture of their read outputs.

The golden files under ``tests/fixtures/app_model_baseline`` were captured from
these workspaces before the application model existed. The regression tests
rebuild the workspaces, capture again and require identical normalized output,
which is the compatibility proof for version-1 manifests.
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import date
from pathlib import Path
import re
from typing import Any
from unittest.mock import Mock, patch
from uuid import UUID

import yaml

from prism_cli import cli
from prism_cli.board_service import BoardService
from prism_cli.status import build_status
from prism_cli.wiki_lint import lint_wiki
from prism_cli.workflow_install import apply_install, plan_install
from prism_cli.workspace import inspect_workspace
from tests import real_temp  # noqa: F401
from tests.wiki_files import write_index, write_status_board


CHECK_DATE = date(2026, 9, 22)
FIXED_BOARD_IDS = {
    "full": "6f1c1b0e-3d2a-4a43-9c55-0d0a5b0e7a11",
    "workflow-only": "a2b4c6d8-1e3f-4a5b-8c7d-9e0f1a2b3c4d",
}
ALL_PLATFORMS = ["backend", "web-user-app", "web-admin-portal", "mobile-android", "mobile-ios"]

_FULL_MANIFEST = """schema_version: 2
min_prism_cli_version: 0.3.0
generated_by:
  tool: prism-cli
  prism_cli_version: 0.3.0
  template_source: https://example.invalid/prism.git
  template_version: unversioned
  template_commit: unversioned
  generated_at: '2026-09-22T09:00:00+00:00'
project:
  name: Baseline Full
  slug: baseline-full
  package_identifier: com.example.baselinefull
  description: Baseline full workspace
  auth_methods:
  - google
  - password
  database: postgres
  supporting_services: []
  use_docker: true
  cloud_provider: azure
  web_hosting: cloudflare
  github_org: ''
apps:
  - id: backend
    name: Spring Boot Backend
    stack: spring-backend
    repository: workspace
    path: backend
  - id: web-user-app
    name: User-Facing Web App
    stack: nextjs-web
    repository: workspace
    path: web-user-app
  - id: web-admin-portal
    name: Admin Web Portal
    stack: nextjs-web
    repository: workspace
    path: web-admin-portal
  - id: mobile-android
    name: Android (Kotlin/Compose)
    stack: android-compose
    repository: workspace
    path: mobile-android
  - id: mobile-ios
    name: iOS (Swift/SwiftUI)
    stack: ios-swiftui
    repository: workspace
    path: mobile-ios
app_maturity:
  backend:
    level: baseline
    caveat: ''
  web-user-app:
    level: provisional
    caveat: Generated web deployment requires live Cloudflare validation before treating
      it as deployment-proven.
  web-admin-portal:
    level: provisional
    caveat: Generated web deployment requires live Cloudflare validation before treating
      it as deployment-proven.
  mobile-android:
    level: baseline
    caveat: ''
  mobile-ios:
    level: experimental
    caveat: Generated iOS structure requires local macOS/Xcode validation before treating
      it as build-proven.
paths:
  wiki_root: knowledge/wiki
  intake_root: knowledge/intake
  advisory_board: knowledge/wiki/advisory/BOARD.md
expected_surfaces:
  ai:
  - AGENTS.md
  - CLAUDE.md
  docs:
  - README.md
  workflows:
  - .github/workflows/backend.yml
  - .github/workflows/web-user-app.yml
  - .github/workflows/web-admin-portal.yml
  - .github/workflows/mobile-android.yml
  - .github/workflows/mobile-ios.yml
"""

_FULL_ANSWERS = """\
_src_path: https://example.invalid/prism.git
_commit: unversioned
project_name: Baseline Full
project_slug: baseline-full
package_identifier: com.example.baselinefull
description: Baseline full workspace
platforms:
- backend
- web-user-app
- web-admin-portal
- mobile-android
- mobile-ios
auth_methods:
- google
- password
database: postgres
supporting_services: []
use_docker: true
cloud_provider: azure
web_hosting: cloudflare
github_org: ''
"""


def build_full_workspace(root: Path) -> Path:
    """A generated-style workspace with all five platforms and the workflow installed."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "prism.workspace.yml").write_text(_FULL_MANIFEST, encoding="utf-8")
    (root / ".copier-answers.yml").write_text(_FULL_ANSWERS, encoding="utf-8")
    for platform in ALL_PLATFORMS:
        (root / platform).mkdir()
        (root / platform / ".gitkeep").write_text("", encoding="utf-8")
    (root / ".github" / "workflows").mkdir(parents=True)
    for platform in ALL_PLATFORMS:
        (root / ".github" / "workflows" / f"{platform}.yml").write_text("name: ci\n", encoding="utf-8")
    for name in ("README.md", "AGENTS.md", "Taskfile.yml"):
        (root / name).write_text(f"# {name}\n", encoding="utf-8")
    (root / "docs" / "deployment").mkdir(parents=True)
    (root / "docs" / "deployment" / "cloudflare-setup.md").write_text("# Cloudflare setup\n", encoding="utf-8")
    _install_workflow(root, "full", upgrade=True)
    add_baseline_wiki_content(root, ["backend", "mobile-android", "web-user-app", "mobile-ios"])
    return root


def build_workflow_only_workspace(root: Path) -> Path:
    """A workflow-only workspace scoped to two platforms."""

    root.mkdir(parents=True, exist_ok=True)
    _install_workflow(root, "workflow-only", upgrade=False, name="Baseline WF", platforms=["backend", "mobile-android"])
    add_baseline_wiki_content(root, ["backend", "mobile-android"])
    return root


def _install_workflow(root: Path, kind: str, *, upgrade: bool, name: str | None = None, platforms: list[str] | None = None) -> None:
    with patch("prism_cli.workflow_install.uuid4", return_value=UUID(FIXED_BOARD_IDS[kind])):
        plan = plan_install(root, name=name, apps=platforms, upgrade=upgrade)
        receipt = apply_install(root, plan)
    if receipt["status"] != "applied":
        raise AssertionError(f"Baseline workflow install did not apply: {receipt}")


def _feature(feature_id: str, title: str, status: str, owner: str, apps: list[str], review: str = "not-needed") -> tuple[str, str]:
    frontmatter = {
        "id": feature_id,
        "title": title,
        "status": status,
        "owner": owner,
        "apps": apps,
        "sources": [],
        "advisory-review": review,
    }
    scope = "\n".join(f"- **{app}**: Deliver the {title.lower()} for {app}." for app in apps)
    body = (
        f"## Summary\n{title} gives reviewers one place to record an outcome.\n\n"
        "## User story\nAs a reviewer, I want to record an outcome, so that follow-up is clear.\n\n"
        "## Acceptance criteria\n- [ ] The outcome can be recorded.\n- [ ] The outcome can be read back.\n\n"
        "## Open questions\n| # | Question | Owner | Status |\n|---|----------|-------|--------|\n"
        "| 1 | Which outcomes are allowed? | po | open |\n\n"
        f"## App scope\n{scope}\n\n"
        "## API surface\nNone\n"
    )
    page = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n\n{body}"
    return f"knowledge/wiki/features/{feature_id}-{title.lower().replace(' ', '-')}.md", page


def add_baseline_wiki_content(root: Path, wide_scope: list[str]) -> None:
    """Three features in different states, a requirement page and a design page."""

    (root / "knowledge/wiki/SETTINGS.md").write_text("---\nwiki-stale-after-days: 36500\n---\n", encoding="utf-8")
    features = [
        _feature("F-001", "Outcome capture", "raw", "po", ["backend"]),
        _feature("F-002", "Outcome review", "in-design", "designer", wide_scope),
        _feature("F-003", "Outcome export", "in-dev", "dev", ["backend", wide_scope[1]]),
    ]
    rows = []
    for relative, page in features:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page, encoding="utf-8")
        frontmatter = yaml.safe_load(page.split("---", 2)[1])
        rows.append(
            f"| {frontmatter['id']} | {frontmatter['title']} | {frontmatter['status']} | {frontmatter['owner']} | not-needed |"
        )
    requirements = root / "knowledge/wiki/app-requirements"
    requirements.mkdir(parents=True, exist_ok=True)
    (requirements / "F-003-backend.md").write_text(
        "---\nfeature-id: F-003\napp: backend\nstatus: in-progress\n---\n\n"
        "## What to build\nStore the export request.\n\n## Acceptance criteria\n- The request is stored.\n",
        encoding="utf-8",
    )
    write_status_board(root, "\n".join(rows) + "\n")
    write_index(root)


def _quiet_clock() -> Mock:
    clock = Mock(wraps=date)
    clock.today.return_value = CHECK_DATE
    return clock


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_SPACES = re.compile(r"[ \t]+")


def normalize_text(text: str, root: Path) -> str:
    """Remove volatile values: absolute paths, UUIDs, timestamps, digests and padding."""

    for variant in (str(root), root.as_posix()):
        text = text.replace(variant, "<ROOT>")
    text = _UUID.sub("<uuid>", text)
    text = _TIMESTAMP.sub("<timestamp>", text)
    text = _SHA256.sub("sha256:<digest>", text)
    text = text.replace("\\", "/")
    return _SPACES.sub(" ", text)


def normalize_json(value: Any, root: Path) -> Any:
    """Normalize every string in a JSON-like value; mapping keys are sorted."""

    if isinstance(value, str):
        return normalize_text(value, root)
    if isinstance(value, dict):
        return {normalize_text(str(key), root): normalize_json(item, root) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item, root) for item in value]
    return value


def _run_cli(argv: list[str]) -> dict[str, Any]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = cli.main(argv)
    return {"exit": code, "output": buffer.getvalue()}


def _doctor_workspace_part(output: str) -> str:
    """Keep the workspace and shared-board sections; tool checks depend on the machine."""

    start = output.index("+ Workspace")
    lines: list[str] = []
    for line in output[start:].splitlines():
        if line.rstrip() in {"Core", "Workflow", "Backend", "Web", "Build Tools", "iOS"}:
            break
        # The default board port and the grant hint depend on the machine and workspace path.
        if "board port" in line or line.lstrip().startswith("Fix:"):
            continue
        lines.append(line)
    return "\n".join(lines)


def capture_cli(root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    status = _run_cli(["status", str(root), "--json"])
    result["status-json"] = {"exit": status["exit"], "json": normalize_json(json.loads(status["output"]), root)}
    lint = _run_cli(["wiki", "lint", str(root), "--json"])
    result["wiki-lint-json"] = {"exit": lint["exit"], "json": normalize_json(json.loads(lint["output"]), root)}
    validate = _run_cli(["validate", str(root)])
    result["validate"] = {"exit": validate["exit"], "output": normalize_text(validate["output"], root)}
    doctor = _run_cli(["doctor", "--workspace", str(root)])
    result["doctor-workspace"] = {"exit": doctor["exit"], "output": normalize_text(_doctor_workspace_part(doctor["output"]), root)}
    return result


def capture_board(root: Path) -> dict[str, Any]:
    """Workspace and status reads through the in-process service API."""

    from prism_cli.board_reads import list_workspace, query

    captured: dict[str, Any] = {}
    with BoardService(root).start() as service:
        captured["compatibility"] = service.compatibility()
        grant = service.create_participant("Baseline reader", "human", writable=True)
        actor = service.authenticate(grant["token"])
        discover = service.discover(actor)
        captured["discover-board"] = discover["board"]
        captured["discover-participant-scopes"] = discover["participant"]["scopes"]
        captured["discover-skill-names"] = sorted(item["name"] for item in discover["skills"])
        captured["identity-app-ids"] = list(service._app_ids)
        captured["list-knowledge"] = [item["path"] for item in list_workspace(service, actor, "knowledge")["files"]]
        for kind in ("lint", "blockers"):
            captured[f"query-{kind}"] = query(service, actor, kind)
        captured["query-show-F-001"] = query(service, actor, "show", "F-001")
        for app_id in service._app_ids:
            captured[f"query-app-{app_id}"] = query(service, actor, "app", app_id)
        for action in ("po-handoff", "design-handoff", "dev-done"):
            feature = "F-001" if action == "po-handoff" else "F-002" if action == "design-handoff" else "F-003"
            captured[f"query-preflight-{action}"] = query(service, actor, "transition-preflight", feature, action)
    return normalize_json(captured, root)


def capture_workspace(root: Path) -> dict[str, Any]:
    """Everything the compatibility proof compares, after normalization."""

    clock = _quiet_clock()
    with patch("prism_cli.wiki_lint.date", clock), patch("prism_cli.wiki_transitions.date", clock):
        inspection = inspect_workspace(root)
        return {
            "inspection": normalize_json(
                {
                    "app_ids": inspection.app_ids,
                    "filesystem_platforms": inspection.filesystem_platforms,
                    "manifest_app_ids": inspection.manifest.app_ids if inspection.manifest else None,
                    "app_maturity": inspection.manifest.app_maturity if inspection.manifest else None,
                    "diagnostics": [item.to_dict() for item in inspection.contract_diagnostics],
                },
                root,
            ),
            "status": normalize_json(build_status(root).to_dict(), root),
            "lint": normalize_json(lint_wiki(root).to_dict(), root),
            "cli": capture_cli(root),
            "board": capture_board(root),
        }
