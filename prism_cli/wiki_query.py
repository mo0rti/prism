"""Read/query surfaces for Prism generated-project wiki facts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prism_cli.wiki_index import INDEX_FILE, ROOT_PAGE_KINDS, page_group, parse_index_entries
from prism_cli.wiki_bugs import ACTIVE_BUG_STATUSES, read_bug_pages
from prism_cli.wiki_lint import WIKI_BLOCKER_CODES, WikiDiagnostic, lint_wiki
from prism_cli.wiki_model import (
    AppRequirementPage,
    FeaturePage,
    load_markdown_page,
    parse_criteria,
    parse_open_question_rows,
    read_feature_pages,
    read_app_requirement_pages,
    within_wiki_read_scope,
)
from prism_cli.workspace import detect_workspace_kind, inspect_workspace


ACTIVE_APP_STATUSES = {"ready-for-design", "in-design", "ready-for-dev", "in-dev", "ready-for-qa", "in-qa", "ready-for-release"}
SEARCH_DIRECTORIES = {
    "feature": "features",
    "persona": "personas",
    "business-rule": "business-rules",
    "design": "design",
    "technical-design": "technical-design",
    "app-requirement": "app-requirements",
    "api-contract": "api-contracts",
    "bug": "bugs",
    "incident": "incidents",
    "decision": "decisions",
    "topic": "topics",
    "research": "research",
    "plan": "plans",
}
# The type a search result reports for a page found through the index, by the page's index group.
_INDEX_GROUP_TYPES = {
    "features": "feature",
    "personas": "persona",
    "business-rules": "business-rule",
    "design": "design",
    "technical-design": "technical-design",
    "app-requirements": "app-requirement",
    "api-contracts": "api-contract",
    "bugs": "bug",
    "incidents": "incident",
    "decisions": "decision",
    "topics": "topic",
    "research": "research",
    "plans": "plan",
    "advisory": "advisory",
    "direction": "direction",
    "meta": "meta",
}
from prism_cli.wiki_links import (  # noqa: E402
    linked_context_for_feature as _shared_linked_context_for_feature,
    markdown_files as _shared_markdown_files,
    page_references_feature as _shared_page_references_feature,
)


@within_wiki_read_scope
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
            for requirement in read_app_requirement_pages(wiki_root)
            if requirement.feature_id == feature.feature_id
        ]
        linked_context = _linked_context_for_feature(wiki_root, feature.feature_id)
        facts["feature"] = _feature_to_dict(feature, requirements, linked_context)
        sources.append(str(feature.page.path))
        sources.extend(str(requirement.page.path) for requirement in requirements)
        for paths in linked_context.values():
            sources.extend(paths)

    return _envelope(workspace_root, "wiki show", diagnostics, facts, sources)


@within_wiki_read_scope
def wiki_blockers(root: Path) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    lint_result = lint_wiki(workspace_root)
    blockers = [diagnostic.to_dict() for diagnostic in lint_result.diagnostics if diagnostic.code in WIKI_BLOCKER_CODES]
    facts = {
        "blocker_count": len(blockers),
        "blockers": blockers,
    }
    return _envelope(workspace_root, "wiki blockers", lint_result.diagnostics, facts, [str(workspace_root / "knowledge" / "wiki")], blockers)


@within_wiki_read_scope
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

    owner_bugs = [bug for bug in read_bug_pages(wiki_root) if bug.owner == owner and bug.status in ACTIVE_BUG_STATUSES]
    facts = {
        "owner": owner,
        "feature_count": len(owner_features),
        "features": [_feature_summary(feature) for feature in owner_features],
        "open_question_count": len(owner_questions),
        "open_questions": owner_questions,
        "bug_count": len(owner_bugs),
        "bugs": [
            {
                "id": bug.bug_id,
                "title": bug.title,
                "status": bug.status,
                "owner": bug.owner,
                "severity": bug.severity,
                "blocking": bug.blocking,
                "apps": bug.apps,
                "feature": bug.feature,
                "deferred": bug.deferred,
                "path": str(bug.page.path),
            }
            for bug in owner_bugs
        ],
    }
    sources = [str(feature.page.path) for feature in owner_features]
    sources.extend(question["path"] for question in owner_questions)
    sources.extend(str(bug.page.path) for bug in owner_bugs)
    return _envelope(workspace_root, "wiki owner", lint_result.diagnostics, facts, _unique([str(wiki_root), *sources]))


@within_wiki_read_scope
def wiki_app(root: Path, app_id: str) -> dict[str, Any]:
    workspace_root = root.expanduser().resolve()
    wiki_root = workspace_root / "knowledge" / "wiki"
    lint_result = lint_wiki(workspace_root)
    features = [
        feature
        for feature in read_feature_pages(wiki_root)
        if app_id in feature.apps and feature.status in ACTIVE_APP_STATUSES
    ]
    requirements = [
        requirement
        for requirement in read_app_requirement_pages(wiki_root)
        if requirement.app == app_id
    ]
    facts = {
        "app": app_id,
        "feature_count": len(features),
        "features": [_feature_summary(feature) for feature in features],
        "app_requirement_count": len(requirements),
        "app_requirements": [_requirement_to_dict(requirement) for requirement in requirements],
    }
    sources = [str(wiki_root)]
    sources.extend(str(feature.page.path) for feature in features)
    sources.extend(str(requirement.page.path) for requirement in requirements)
    return _envelope(workspace_root, "wiki app", lint_result.diagnostics, facts, _unique(sources))


@within_wiki_read_scope
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

    facts = {
        "query": query,
        "result_count": len(results),
        "index_match_count": sum(1 for result in results if "index_line" in result),
        "results": results,
    }
    index_path = wiki_root / INDEX_FILE
    sources = _unique([str(wiki_root), *([str(index_path)] if index_path.is_file() else []), *[result["path"] for result in results]])
    return _envelope(workspace_root, "wiki search", diagnostics, facts, sources)


def _envelope(
    root: Path,
    command: str,
    diagnostics: list[WikiDiagnostic],
    facts: dict[str, Any],
    sources: list[str],
    blocker_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    inspection = inspect_workspace(root)
    all_diagnostics = [
        _workspace_diag_to_wiki_diag(diagnostic)
        for diagnostic in inspection.contract_diagnostics
    ]
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
            "project_name": inspection.project_name,
            **({"purpose": inspection.model.purpose} if inspection.model.purpose else {}),
            "apps": inspection.apps,
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
    requirements: list[AppRequirementPage],
    linked_context: dict[str, list[str]],
) -> dict[str, Any]:
    rows, errors = parse_open_question_rows(feature.page.body)
    return {
        **_feature_summary(feature),
        "frontmatter": _json_safe(dict(feature.page.frontmatter)),
        "open_questions": rows,
        "open_question_parse_errors": errors,
        "criteria": [
            {"id": item.id, "revision": item.revision, "applies_to": list(item.applies_to), "integration": item.integration}
            for item in parse_criteria(feature.page.body, feature.feature_id)
            if item.id is not None and item.revision is not None
        ],
        "linked_context": linked_context,
        "app_requirements": [_requirement_to_dict(requirement) for requirement in requirements],
    }


def _feature_summary(feature: FeaturePage) -> dict[str, Any]:
    return {
        "id": feature.feature_id,
        "title": feature.title,
        "status": feature.status,
        "owner": feature.owner,
        "advisory_review": feature.advisory_review,
        "apps": feature.apps,
        "path": str(feature.page.path),
    }


def _requirement_to_dict(requirement: AppRequirementPage) -> dict[str, Any]:
    return {
        "feature_id": requirement.feature_id,
        "app": requirement.app,
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
    """Search the wiki, reading the general index first.

    The index lines that contain the query name their pages without opening them. Those pages come
    first, in index order, each with its index line and `index` among its matched fields; every page
    of the page folders and the wiki root is then searched by its own fields, as before, so a page
    that is not indexed, or whose line lacks the query, is still found.
    """

    results: list[dict[str, Any]] = []
    seen: set[Path] = set()

    index_path = wiki_root / INDEX_FILE
    index_hits: list[tuple[str, str]] = []
    if index_path.is_file():
        try:
            text = index_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            text = ""
        index_hits = [(entry.target, entry.line) for entry in parse_index_entries(text) if query in entry.line.lower()]
    for target, line in index_hits:
        path = wiki_root / target
        group = page_group(target)
        if group is None or group == "project-docs" or not path.is_file() or path in seen:
            continue
        seen.add(path)
        page = load_markdown_page(path)
        results.append(_search_result(_INDEX_GROUP_TYPES[group], path, page, ["index", *_matched_fields(query, _page_fields(path, page))], line))

    searched: list[tuple[str, Path]] = []
    for page_type, directory in SEARCH_DIRECTORIES.items():
        searched.extend((page_type, path) for path in _markdown_files(wiki_root / directory))
    searched.extend((kind, wiki_root / name) for name, kind in ROOT_PAGE_KINDS.items() if (wiki_root / name).is_file())
    for page_type, path in searched:
        if path in seen:
            continue
        page = load_markdown_page(path)
        matched_fields = _matched_fields(query, _page_fields(path, page))
        if matched_fields:
            seen.add(path)
            results.append(_search_result(page_type, path, page, matched_fields, None))
    return results


def _page_fields(path: Path, page: Any) -> dict[str, str]:
    fields = {"filename": path.name, "body": page.body}
    for key, value in page.frontmatter.items():
        if isinstance(value, (str, int, float, bool)):
            fields[f"frontmatter.{key}"] = str(value)
        elif isinstance(value, list):
            fields[f"frontmatter.{key}"] = " ".join(str(item) for item in value)
    return fields


def _search_result(page_type: str, path: Path, page: Any, matched_fields: list[str], index_line: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": page_type, "path": str(path), "matched_fields": matched_fields}
    if index_line is not None:
        result["index_line"] = index_line
    for key in ("id", "title", "feature-id", "app", "status", "owner"):
        value = page.frontmatter.get(key)
        if isinstance(value, str):
            result[key.replace("-", "_")] = value
    return result


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
