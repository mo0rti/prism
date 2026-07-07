"""Typed-ish readers for Prism wiki markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


VALID_FEATURE_STATUSES = {"raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "done"}
VALID_FEATURE_OWNERS = {"po", "designer", "dev", "none"}
VALID_OPEN_QUESTION_OWNERS = {"po", "designer", "dev"}
VALID_ADVISORY_REVIEW_STATES = {"not-needed", "pending", "done", "skipped"}
VALID_PLATFORM_IDS = {"backend", "mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"}
VALID_PLATFORM_REQUIREMENT_STATUSES = {"pending", "in-progress", "done"}


@dataclass(frozen=True)
class MarkdownPage:
    path: Path
    frontmatter: dict[str, Any]
    body: str
    parse_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeaturePage:
    page: MarkdownPage

    @property
    def feature_id(self) -> str:
        value = self.page.frontmatter.get("id")
        if isinstance(value, str):
            return value
        match = re.match(r"^(F-\d+)(?:-|$)", self.page.path.stem)
        return match.group(1) if match else self.page.path.stem

    @property
    def title(self) -> str:
        value = self.page.frontmatter.get("title")
        return value if isinstance(value, str) else self.page.path.stem

    @property
    def status(self) -> str | None:
        value = self.page.frontmatter.get("status")
        return value if isinstance(value, str) else None

    @property
    def owner(self) -> str | None:
        value = self.page.frontmatter.get("owner")
        return value if isinstance(value, str) else None

    @property
    def advisory_review(self) -> str | None:
        value = self.page.frontmatter.get("advisory-review")
        return value if isinstance(value, str) else None

    @property
    def platforms(self) -> list[str]:
        value = self.page.frontmatter.get("platforms")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]


@dataclass(frozen=True)
class PlatformRequirementPage:
    page: MarkdownPage

    @property
    def feature_id(self) -> str | None:
        value = self.page.frontmatter.get("feature-id")
        return value if isinstance(value, str) else None

    @property
    def platform(self) -> str | None:
        value = self.page.frontmatter.get("platform")
        return value if isinstance(value, str) else None

    @property
    def status(self) -> str | None:
        value = self.page.frontmatter.get("status")
        return value if isinstance(value, str) else None


@dataclass(frozen=True)
class IndexFeatureRow:
    feature_id: str
    title: str
    status: str
    owner: str
    advisory_review: str
    path: Path


FRONTMATTER_PATTERN = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


def read_markdown_page(path: Path) -> MarkdownPage:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return MarkdownPage(path=path, frontmatter={}, body="", parse_errors=[f"Unable to read file: {exc}"])

    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return MarkdownPage(path=path, frontmatter={}, body=text, parse_errors=["Missing YAML frontmatter."])

    raw_frontmatter, body = match.groups()
    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        return MarkdownPage(path=path, frontmatter={}, body=body, parse_errors=[f"Invalid YAML frontmatter: {exc}"])

    if not isinstance(loaded, dict):
        return MarkdownPage(path=path, frontmatter={}, body=body, parse_errors=["YAML frontmatter must be a mapping."])

    return MarkdownPage(path=path, frontmatter=loaded, body=body)


def read_feature_pages(wiki_root: Path) -> list[FeaturePage]:
    features_dir = wiki_root / "features"
    if not features_dir.exists():
        return []
    return [
        FeaturePage(read_markdown_page(path))
        for path in sorted(features_dir.glob("*.md"))
        if not path.name.startswith("_")
    ]


def read_platform_requirement_pages(wiki_root: Path) -> list[PlatformRequirementPage]:
    requirements_dir = wiki_root / "platform-requirements"
    if not requirements_dir.exists():
        return []
    return [
        PlatformRequirementPage(read_markdown_page(path))
        for path in sorted(requirements_dir.glob("*.md"))
        if not path.name.startswith("_")
    ]


def parse_index_feature_rows(index_path: Path) -> tuple[list[IndexFeatureRow], list[str]]:
    try:
        text = index_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"Unable to read index.md: {exc}"]

    rows: list[IndexFeatureRow] = []
    errors: list[str] = []
    in_feature_table = False
    header_seen = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## Other wiki pages"):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        if cells[:6] == ["ID", "Feature", "Status", "Owner", "Board Review", "Introduced"]:
            in_feature_table = True
            header_seen = True
            continue
        if not in_feature_table:
            continue
        if _is_separator_row(cells):
            continue
        feature_id, title, status, owner, advisory_review, _introduced = cells[:6]
        if not feature_id:
            errors.append("index.md contains a feature row with an empty ID.")
            continue
        rows.append(
            IndexFeatureRow(
                feature_id=feature_id,
                title=title,
                status=status,
                owner=owner,
                advisory_review=advisory_review,
                path=index_path,
            )
        )

    if not header_seen:
        errors.append("index.md is missing the feature status board table.")
    return rows, errors


def parse_open_question_rows(body: str) -> tuple[list[dict[str, str]], list[str]]:
    lines = body.splitlines()
    section_lines: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section:
                break
            in_section = stripped.lower() == "## open questions"
            continue
        if in_section:
            section_lines.append(line)

    if not section_lines:
        return [], []

    rows: list[dict[str, str]] = []
    errors: list[str] = []
    header_seen = False
    for raw_line in section_lines:
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            errors.append(f"Malformed open questions table row: {line}")
            continue
        if cells[:4] == ["#", "Question", "Owner", "Status"]:
            header_seen = True
            continue
        if _is_separator_row(cells):
            continue
        rows.append({"number": cells[0], "question": cells[1], "owner": cells[2], "status": cells[3]})

    if rows and not header_seen:
        errors.append("Open questions table is missing the expected header row.")
    return rows, errors


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    stripped = [cell.strip() for cell in cells]
    return any(stripped) and all(re.fullmatch(r":?-+:?", cell) for cell in stripped if cell)
