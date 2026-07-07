"""Read/query surfaces for Prism generated-project wiki facts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, WikiDiagnostic, lint_wiki
from prism_cli.wiki_model import (
    FeaturePage,
    PlatformRequirementPage,
    parse_open_question_rows,
    read_feature_pages,
    read_markdown_page,
    read_platform_requirement_pages,
)
from prism_cli.workspace import detect_workspace_kind, load_workspace


ACTIVE_PLATFORM_STATUSES = {"ready-for-design", "in-design", "ready-for-dev", "in-dev"}
SEARCH_DIRECTORIES = {
    "feature": "features",
    "persona": "personas",
    "business-rule": "business-rules",
    "design": "design",
    "platform-requirement": "platform-requirements",
    "api-contract": "api-contracts",
    "decision": "decisions",
}
from prism_cli.wiki_links import (  # noqa: E402  (kept here so existing imports stay stable)
    LINKED_CONTEXT_DIRECTORIES,
    linked_context_for_feature as _shared_linked_context_for_feature,
    markdown_files as _shared_markdown_files,
    page_references_feature as _shared_page_references_feature,
)


def wiki_show(root: Path, feature_id: str) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    wiki_root = workspace_root / "knowledge" / "wiki"
    lint_result = lint_wiki(workspace_root)
    features = read_feature_pages(wiki_root)
    feature = _find_feature(features, feature_id)
    diagnostics = list(lint_result.diagnostics)
    facts: dict[str, Any] = {"feature": None}
    sources = [str(wiki_root)]

    if feature is None:
        diagnostics.append(
            _diag(
                "feature-not-found",
                "error",
                wiki_root / "features",
                f"No feature page found for `{feature_id}`.",
                feature_id,
            )
        )
    else:
        requirements = [
            requirement
            for requirement in read_platform_requirement_pages(wiki_root)
            if requirement.feature_id == feature.feature_id
        ]
        linked_context = _linked_context_for_feature(wiki_root, feature.feature_id)
        facts["feature"] = _feature_to_dict(feature, requirements, linked_context)
        sources.append(str(feature.page.path))
        sources.extend(str(requirement.page.path) for requirement in requirements)
        for paths in linked_context.values():
            sources.extend(paths)

    return _envelope(workspace_root, "wiki show", diagnostics, facts, sources)


def wiki_blockers(root: Path) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    lint_result = lint_wiki(workspace_root)
    blockers = [diagnostic.to_dict() for diagnostic in lint_result.diagnostics if diagnostic.code in WIKI_BLOCKER_CODES]
    facts = {
        "blocker_count": len(blockers),
        "blockers": blockers,
    }
    return _envelope(workspace_root, "wiki blockers", lint_result.diagnostics, facts, [str(workspace_root / "knowledge" / "wiki")], blockers)


def wiki_owner(root: Path, owner: str) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    wiki_root = workspace_root / "knowledge" / "wiki"
    lint_result = lint_wiki(workspace_root)
    features = read_feature_pages(wiki_root)
    owner_features = [feature for feature in features if feature.owner == owner]
    owner_questions: list[dict[str, Any]] = []

    for feature in features:
        rows, _errors = parse_open_question_rows(feature.page.body)
        for row in rows:
            if row["owner"] == owner and row["status"] == "open":
                owner_questions.append(
                    {
                        "feature_id": feature.feature_id,
                        "feature_title": feature.title,
                        "number": row["number"],
                        "question": row["question"],
                        "path": str(feature.page.path),
                    }
                )

    facts = {
        "owner": owner,
        "feature_count": len(owner_features),
        "features": [_feature_summary(feature) for feature in owner_features],
        "open_question_count": len(owner_questions),
        "open_questions": owner_questions,
    }
    sources = [str(feature.page.path) for feature in owner_features]
    sources.extend(question["path"] for question in owner_questions)
    return _envelope(workspace_root, "wiki owner", lint_result.diagnostics, facts, _unique([str(wiki_root), *sources]))


def wiki_platform(root: Path, platform_id: str) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    wiki_root = workspace_root / "knowledge" / "wiki"
    lint_result = lint_wiki(workspace_root)
    features = [
        feature
        for feature in read_feature_pages(wiki_root)
        if platform_id in feature.platforms and feature.status in ACTIVE_PLATFORM_STATUSES
    ]
    requirements = [
        requirement
        for requirement in read_platform_requirement_pages(wiki_root)
        if requirement.platform == platform_id
    ]
    facts = {
        "platform": platform_id,
        "feature_count": len(features),
        "features": [_feature_summary(feature) for feature in features],
        "platform_requirement_count": len(requirements),
        "platform_requirements": [_requirement_to_dict(requirement) for requirement in requirements],
    }
    sources = [str(wiki_root)]
    sources.extend(str(feature.page.path) for feature in features)
    sources.extend(str(requirement.page.path) for requirement in requirements)
    return _envelope(workspace_root, "wiki platform", lint_result.diagnostics, facts, _unique(sources))


def wiki_search(root: Path, query: str) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    wiki_root = workspace_root / "knowledge" / "wiki"
    lint_result = lint_wiki(workspace_root)
    diagnostics = list(lint_result.diagnostics)
    normalized_query = query.strip().lower()
    results: list[dict[str, Any]] = []

    if not normalized_query:
        diagnostics.append(_diag("empty-search-query", "error", wiki_root, "Search query must not be empty."))
    else:
        results = _search_wiki_pages(wiki_root, normalized_query)

    facts = {"query": query, "result_count": len(results), "results": results}
    sources = _unique([str(wiki_root), *[result["path"] for result in results]])
    return _envelope(workspace_root, "wiki search", diagnostics, facts, sources)


def _envelope(
    root: Path,
    command: str,
    diagnostics: list[WikiDiagnostic],
    facts: dict[str, Any],
    sources: list[str],
    blocker_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    workspace = load_workspace(root)
    all_diagnostics = [_workspace_diag_to_wiki_diag(diagnostic) for diagnostic in workspace.diagnostics]
    all_diagnostics.extend(diagnostics)
    confidence = "error" if any(diagnostic.severity == "error" for diagnostic in all_diagnostics) else "degraded" if all_diagnostics else "high"
    return {
        "schema_version": 1,
        "experimental": True,
        "command": command,
        "root": str(root),
        "confidence": confidence,
        "workspace": {
            "kind": detect_workspace_kind(root),
            "project_name": workspace.manifest.project_name if workspace.manifest else None,
            "platforms": workspace.manifest.platforms if workspace.manifest else [],
        },
        "facts": facts,
        "blocker_facts": blocker_facts if blocker_facts is not None else [
            diagnostic.to_dict()
            for diagnostic in all_diagnostics
            if diagnostic.code in WIKI_BLOCKER_CODES
        ],
        "required_obligations": [
            {"code": diagnostic.code, "path": diagnostic.path}
            for diagnostic in all_diagnostics
            if diagnostic.code in WIKI_BLOCKER_CODES
        ],
        "sources": _unique(sources),
        "diagnostics": [diagnostic.to_dict() for diagnostic in all_diagnostics],
    }


def _feature_to_dict(
    feature: FeaturePage,
    requirements: list[PlatformRequirementPage],
    linked_context: dict[str, list[str]],
) -> dict[str, Any]:
    rows, errors = parse_open_question_rows(feature.page.body)
    return {
        **_feature_summary(feature),
        "frontmatter": _json_safe(dict(feature.page.frontmatter)),
        "open_questions": rows,
        "open_question_parse_errors": errors,
        "linked_context": linked_context,
        "platform_requirements": [_requirement_to_dict(requirement) for requirement in requirements],
    }


def _feature_summary(feature: FeaturePage) -> dict[str, Any]:
    return {
        "id": feature.feature_id,
        "title": feature.title,
        "status": feature.status,
        "owner": feature.owner,
        "advisory_review": feature.advisory_review,
        "platforms": feature.platforms,
        "path": str(feature.page.path),
    }


def _requirement_to_dict(requirement: PlatformRequirementPage) -> dict[str, Any]:
    return {
        "feature_id": requirement.feature_id,
        "platform": requirement.platform,
        "status": requirement.status,
        "path": str(requirement.page.path),
    }


def _find_feature(features: list[FeaturePage], feature_id: str) -> FeaturePage | None:
    normalized = feature_id.strip().lower()
    for feature in features:
        if feature.feature_id.lower() == normalized:
            return feature
    return None


def _matched_fields(query: str, fields: dict[str, str]) -> list[str]:
    return [field for field, value in fields.items() if query in value.lower()]


def _search_wiki_pages(wiki_root: Path, query: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for page_type, directory in SEARCH_DIRECTORIES.items():
        for path in _markdown_files(wiki_root / directory):
            page = read_markdown_page(path)
            fields = {
                "filename": path.name,
                "body": page.body,
            }
            for key, value in page.frontmatter.items():
                if isinstance(value, (str, int, float, bool)):
                    fields[f"frontmatter.{key}"] = str(value)
                elif isinstance(value, list):
                    fields[f"frontmatter.{key}"] = " ".join(str(item) for item in value)
            matched_fields = _matched_fields(query, fields)
            if not matched_fields:
                continue
            result: dict[str, Any] = {
                "type": page_type,
                "path": str(path),
                "matched_fields": matched_fields,
            }
            for key in ("id", "title", "feature-id", "platform", "status", "owner"):
                value = page.frontmatter.get(key)
                if isinstance(value, str):
                    result[key.replace("-", "_")] = value
            results.append(result)
    return results


def _linked_context_for_feature(wiki_root: Path, feature_id: str) -> dict[str, list[str]]:
    return _shared_linked_context_for_feature(wiki_root, feature_id)


def _page_references_feature(frontmatter: dict[str, Any], body: str, filename: str, feature_id: str) -> bool:
    return _shared_page_references_feature(frontmatter, body, filename, feature_id)


def _markdown_files(path: Path) -> list[Path]:
    return _shared_markdown_files(path)


def _workspace_diag_to_wiki_diag(diagnostic: Any) -> WikiDiagnostic:
    return WikiDiagnostic(
        code=diagnostic.code,
        severity=diagnostic.severity,
        path=diagnostic.path,
        message=diagnostic.message,
    )


def _diag(code: str, severity: str, path: Path, message: str, feature_id: str | None = None) -> WikiDiagnostic:
    return WikiDiagnostic(code=code, severity=severity, path=str(path), message=message, feature_id=feature_id)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# Public alias so sibling surfaces (wiki_graph) reuse the exact same envelope.
build_envelope = _envelope
