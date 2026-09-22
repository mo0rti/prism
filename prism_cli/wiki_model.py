"""Typed-ish readers for Prism wiki markdown files."""

from __future__ import annotations

import re
from datetime import date, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml


VALID_FEATURE_STATUSES = {"raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "done"}
VALID_FEATURE_OWNERS = {"po", "designer", "dev", "none"}
VALID_OPEN_QUESTION_OWNERS = {"po", "designer", "dev"}
VALID_ADVISORY_REVIEW_STATES = {"not-needed", "pending", "done", "skipped"}
VALID_PLATFORM_IDS = {"backend", "mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"}
VALID_PLATFORM_REQUIREMENT_STATUSES = {"pending", "in-progress", "done"}
UI_PLATFORM_IDS = {"mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"}
DEFAULT_WIKI_STALE_AFTER_DAYS = 14
REVALIDATION_DOMAINS = {
    "specification",
    "design",
    "implementation",
    "tests",
    "release",
}
DELIVERY_EVIDENCE_COLUMNS = ("platform", "implementation", "tests", "release")


@dataclass(frozen=True)
class MarkdownPage:
    path: Path
    frontmatter: dict[str, Any]
    body: str
    parse_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WikiSettings:
    """Read-only settings shared by wiki lint and other read surfaces."""

    stale_after_days: int
    path: Path
    used_fallback: bool = False
    diagnostics: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FeaturePage:
    page: MarkdownPage

    @property
    def feature_id(self) -> str:
        value = self.page.frontmatter.get("id")
        if isinstance(value, str) and value.strip():
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
MARKDOWN_LINK_PATTERN = re.compile(
    r"(?<!!)\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))",
)
FEATURE_ID_PATTERN = re.compile(r"\bF-\d+\b")


def read_markdown_page(path: Path) -> MarkdownPage:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return MarkdownPage(path=path, frontmatter={}, body="", parse_errors=[f"Unable to read file: {exc}"])

    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return MarkdownPage(path=path, frontmatter={}, body=text, parse_errors=["Missing YAML frontmatter."])

    raw_frontmatter, body = match.groups()
    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except (yaml.YAMLError, TypeError, ValueError, OverflowError) as exc:
        return MarkdownPage(path=path, frontmatter={}, body=body, parse_errors=[f"Invalid YAML frontmatter: {exc}"])

    if not isinstance(loaded, dict):
        return MarkdownPage(path=path, frontmatter={}, body=body, parse_errors=["YAML frontmatter must be a mapping."])

    return MarkdownPage(path=path, frontmatter=loaded, body=body)


def read_wiki_settings(wiki_root: Path) -> WikiSettings:
    """Read the canonical stale-page setting with its documented fallback."""

    settings_path = wiki_root / "SETTINGS.md"
    if not settings_path.exists():
        return WikiSettings(
            stale_after_days=DEFAULT_WIKI_STALE_AFTER_DAYS,
            path=settings_path,
            used_fallback=True,
            diagnostics=(
                (
                    "missing-wiki-settings",
                    f"Missing SETTINGS.md; using wiki-stale-after-days: {DEFAULT_WIKI_STALE_AFTER_DAYS}.",
                ),
            ),
        )

    page = read_markdown_page(settings_path)
    if page.parse_errors:
        return WikiSettings(
            stale_after_days=DEFAULT_WIKI_STALE_AFTER_DAYS,
            path=settings_path,
            used_fallback=True,
            diagnostics=tuple(("invalid-wiki-settings", message) for message in page.parse_errors),
        )

    if "wiki-stale-after-days" not in page.frontmatter:
        return WikiSettings(
            stale_after_days=DEFAULT_WIKI_STALE_AFTER_DAYS,
            path=settings_path,
            used_fallback=True,
            diagnostics=(
                (
                    "missing-wiki-setting",
                    f"SETTINGS.md is missing `wiki-stale-after-days`; using {DEFAULT_WIKI_STALE_AFTER_DAYS}.",
                ),
            ),
        )

    value = page.frontmatter["wiki-stale-after-days"]
    parsed: int | None = None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        parsed = int(value.strip())
    if parsed is None:
        return WikiSettings(
            stale_after_days=DEFAULT_WIKI_STALE_AFTER_DAYS,
            path=settings_path,
            used_fallback=True,
            diagnostics=(
                (
                    "invalid-wiki-stale-after-days",
                    f"`wiki-stale-after-days` must be a non-negative integer; using {DEFAULT_WIKI_STALE_AFTER_DAYS}.",
                ),
            ),
        )
    return WikiSettings(stale_after_days=parsed, path=settings_path)


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


def read_markdown_pages(directory: Path) -> list[MarkdownPage]:
    """Read non-template markdown pages in a directory in stable path order."""

    if not directory.exists():
        return []
    return [
        read_markdown_page(path)
        for path in sorted(directory.glob("*.md"), key=lambda item: item.name)
        if not path.name.startswith("_")
    ]


def read_wiki_pages(wiki_root: Path) -> list[MarkdownPage]:
    """Read all markdown pages below a wiki root, including top-level index pages."""

    if not wiki_root.exists():
        return []
    return [
        read_markdown_page(path)
        for path in sorted(
            wiki_root.rglob("*.md"),
            key=lambda item: item.relative_to(wiki_root).as_posix(),
        )
        if not path.name.startswith("_")
    ]


def extract_markdown_links(text: str) -> list[str]:
    """Return markdown link targets without image or reference-style links."""

    return [unquote(match.group(1) or match.group(2)) for match in MARKDOWN_LINK_PATTERN.finditer(text)]


def normalize_feature_id(value: str) -> str:
    """Comparison key; preserve original IDs in displayed facts and diagnostics."""
    return value.strip().lower()


def candidate_relative_markdown_link(source_path: Path, raw_target: str) -> Path | None:
    """Resolve a relative Markdown path, without assigning it to a wiki root."""

    try:
        parsed = urlsplit(raw_target)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or "\x00" in parsed.path or not parsed.path.lower().endswith(".md"):
        return None
    target = Path(parsed.path)
    if target.is_absolute():
        return None
    try:
        return (source_path.parent / target).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def resolve_relative_markdown_link(source_path: Path, raw_target: str, wiki_root: Path) -> Path | None:
    """Resolve a relative markdown target when it stays inside the wiki root."""
    resolved = candidate_relative_markdown_link(source_path, raw_target)
    if resolved is None:
        return None
    try:
        resolved.relative_to(wiki_root.resolve())
    except ValueError:
        return None
    return resolved


def section_text(body: str, heading: str) -> str:
    """Return the body of a level-two markdown section, or an empty string."""

    wanted = heading.strip().lower()
    lines = body.splitlines(keepends=True)
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line.strip())
        if not match:
            continue
        current = match.group(1).strip().lower()
        if start is None:
            if current == wanted:
                start = index + 1
        else:
            end = index
            break
    return "".join(lines[start:end]) if start is not None else ""


def parse_revalidation(value: Any) -> tuple[list[str], list[str]]:
    """Parse the optional current-work revalidation domain list.

    The list is deliberately strict: unknown domains would otherwise make a
    reopened feature appear current while the evaluator has no way to know
    which downstream evidence is pending.
    """

    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], ["`revalidation` must be a list of lifecycle domains."]
    domains: list[str] = []
    errors: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append("Every `revalidation` entry must be a non-empty domain string.")
            continue
        domain = item.strip().lower()
        if domain not in REVALIDATION_DOMAINS:
            errors.append(
                f"`revalidation` contains unsupported domain `{item}`; expected one of {sorted(REVALIDATION_DOMAINS)}."
            )
            continue
        if domain in domains:
            errors.append(f"`revalidation` contains duplicate domain `{domain}`.")
            continue
        domains.append(domain)
    return domains, errors


def parse_delivery_evidence(
    body: str,
    declared_platforms: list[str],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Parse the canonical per-platform delivery evidence table.

    This validates only observable structure and substantive cells.  It does
    not claim that referenced implementation, test, or release artifacts exist;
    the responsible agent must verify those references before writing Done.
    """

    section = section_text(body, "Delivery evidence")
    if not section.strip():
        return {}, ["Required `Delivery evidence` section is missing or empty."]

    table_lines = _visible_evidence_table_lines(section)
    if not table_lines:
        return {}, ["Delivery evidence must contain a markdown table."]

    header: list[str] | None = None
    header_indexes: dict[str, int] = {}
    rows: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        normalized = [re.sub(r"[*_`]+", "", cell).strip().lower() for cell in cells]
        if header is None:
            if len(normalized) == len(DELIVERY_EVIDENCE_COLUMNS) and set(normalized) == set(DELIVERY_EVIDENCE_COLUMNS):
                header = cells
                header_indexes = {column: normalized.index(column) for column in DELIVERY_EVIDENCE_COLUMNS}
                continue
            if _is_separator_row(cells):
                continue
            errors.append("Delivery evidence table is missing the Platform/Implementation/Tests/Release header.")
            continue
        if len(normalized) == len(DELIVERY_EVIDENCE_COLUMNS) and set(normalized) == set(DELIVERY_EVIDENCE_COLUMNS):
            errors.append("Delivery evidence contains more than one header/table.")
            continue
        if _is_separator_row(cells):
            continue
        if len(cells) != len(DELIVERY_EVIDENCE_COLUMNS):
            errors.append("Delivery evidence table rows must contain exactly Platform, Implementation, Tests, and Release cells.")
            continue
        platform = cells[header_indexes["platform"]].strip().lower()
        if not platform:
            errors.append("Every delivery evidence row must name a platform.")
            continue
        if platform in rows:
            errors.append(f"Delivery evidence contains duplicate platform `{platform}` rows.")
            continue
        row = {
            column: cells[index].strip()
            for column, index in header_indexes.items()
        }
        rows[platform] = row
        for column in DELIVERY_EVIDENCE_COLUMNS[1:]:
            if not _substantive_evidence_cell(row[column]):
                errors.append(f"Delivery evidence `{column}` for `{platform}` is empty or still a placeholder.")

    if header is None:
        errors.append("Delivery evidence table has no usable header row.")

    declared = {platform.strip().lower() for platform in declared_platforms if isinstance(platform, str) and platform.strip()}
    missing = sorted(declared - set(rows))
    extra = sorted(set(rows) - declared)
    if missing:
        errors.append("Delivery evidence is missing declared platform(s): " + ", ".join(missing) + ".")
    if extra:
        errors.append("Delivery evidence contains undeclared platform(s): " + ", ".join(extra) + ".")
    return rows, errors


def parse_advisory_required_actions(body: str) -> tuple[list[str], list[str]]:
    """Return unchecked pre-development advisory actions and parse errors."""

    section = section_text(body, "Actions required before dev starts")
    if not section.strip():
        return [], ["Advisory review is missing `Actions required before dev starts`."]
    pending: list[str] = []
    errors: list[str] = []
    visible_lines = _visible_markdown_lines(section)
    if len(visible_lines) == 1 and re.sub(r"[.\s]+$", "", visible_lines[0]).lower() in {
        "none",
        "none required",
        "no actions required",
    }:
        return [], []
    for line in visible_lines:
        if line.startswith("<!--") or line.endswith("-->"):
            continue
        match = re.match(r"^[-*+]\s+\[([ xX])\]\s+(.*)$", line)
        if match:
            action = match.group(2).strip()
            if not action:
                errors.append("Advisory required-action checklist contains an empty item.")
            elif match.group(1) == " ":
                pending.append(action)
            continue
        if re.match(r"^[-*+]\s+", line):
            errors.append("Advisory required actions must use checked or unchecked checklist items.")
            continue
        if line.startswith("|"):
            errors.append("Advisory required actions must be a checklist, not a table row.")
            continue
        errors.append("Advisory required-action section contains an unstructured line.")
    if not pending and not errors and not any(re.match(r"^[-*+]\s+", line) for line in visible_lines):
        errors.append("Advisory required-action section has no checklist items or explicit `None`.")
    return pending, errors


def _visible_evidence_table_lines(section: str) -> list[str]:
    """Return table lines outside fenced code and HTML comments."""

    return [line for line in _visible_markdown_lines(section) if line.startswith("|")]


def _visible_markdown_lines(text: str) -> list[str]:
    """Return non-empty Markdown lines outside fences and HTML comments."""

    visible: list[str] = []
    fenced = False
    in_comment = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```") or line.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
                line = line.split("-->", 1)[1].strip()
            else:
                continue
        while "<!--" in line:
            before, remainder = line.split("<!--", 1)
            if "-->" in remainder:
                line = before + remainder.split("-->", 1)[1]
            else:
                line = before
                in_comment = True
                break
        line = line.strip()
        if line:
            visible.append(line)
    return visible


def _substantive_evidence_cell(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    if not normalized or normalized.startswith("<!--") or normalized.endswith("-->"):
        return False
    if normalized in {"-", "—", "todo", "tbd", "pending", "n/a", "na", "none", "not supplied"}:
        return False
    if re.fullmatch(r"\[[^\]]+\]", normalized):
        return False
    return True


def feature_id_from_path(path: Path) -> str | None:
    """Extract a canonical feature ID from a feature-like filename."""

    match = re.match(r"^(F-\d+)(?:-|$)", path.stem)
    return match.group(1) if match else None


def parse_iso_date(value: Any) -> date | None:
    """Parse YAML date values and ISO date strings without raising."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            return None
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def page_date_field(page: MarkdownPage) -> tuple[str, Any] | None:
    """Return the first known lifecycle date field present on a page."""

    for field_name in ("last-updated", "reviewed", "date", "introduced"):
        if field_name in page.frontmatter:
            return field_name, page.frontmatter[field_name]
    return None


def parse_index_feature_rows(index_path: Path) -> tuple[list[IndexFeatureRow], list[str]]:
    try:
        text = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
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
        if len(cells) != 4:
            errors.append(f"Malformed open questions table row: {line}")
            continue
        if cells[:4] == ["#", "Question", "Owner", "Status"]:
            header_seen = True
            continue
        if _is_separator_row(cells):
            continue
        rows.append({"number": cells[0], "question": cells[1], "owner": cells[2], "status": cells[3]})

    if any(line.strip().startswith("|") for line in section_lines) and not header_seen:
        errors.append("Open questions table is missing the expected header row.")
    return rows, errors


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    stripped = [cell.strip() for cell in cells]
    return any(stripped) and all(re.fullmatch(r":?-+:?", cell) for cell in stripped if cell)
