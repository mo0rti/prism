"""Shared wiki cross-reference helpers used by read/query and graph surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any


LINKED_CONTEXT_DIRECTORIES = {
    "design": "design",
    "api_contracts": "api-contracts",
    "advisory_reviews": "advisory",
    "business_rules": "business-rules",
    "personas": "personas",
    "decisions": "decisions",
}

NON_PAGE_FILENAMES = {"BOARD.md", "_FORMAT.md", "SCHEMA.md", "SETTINGS.md", "index.md", "log.md", "WIKI_REPORT.md"}


def markdown_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return [child for child in sorted(path.glob("*.md")) if not child.name.startswith("_")]


def page_references_feature(frontmatter: dict[str, Any], body: str, filename: str, feature_id: str) -> bool:
    if filename.startswith(f"{feature_id}-") or filename == f"{feature_id}.md":
        return True
    for key in ("id", "feature-id"):
        value = frontmatter.get(key)
        if isinstance(value, str) and value.lower() == feature_id.lower():
            return True
    return feature_id.lower() in body.lower()


def linked_context_for_feature(wiki_root: Path, feature_id: str) -> dict[str, list[str]]:
    from prism_cli.wiki_model import read_markdown_page

    linked_context: dict[str, list[str]] = {key: [] for key in LINKED_CONTEXT_DIRECTORIES}
    for context_key, directory in LINKED_CONTEXT_DIRECTORIES.items():
        for path in markdown_files(wiki_root / directory):
            if path.name in {"BOARD.md", "_FORMAT.md"}:
                continue
            page = read_markdown_page(path)
            if page_references_feature(page.frontmatter, page.body, path.name, feature_id):
                linked_context[context_key].append(str(path))
    return linked_context
