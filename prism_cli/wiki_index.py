"""The general wiki index: one line per page, grouped by kind.

`knowledge/wiki/index.md` lists every wiki page once, as `- [Label](path.md): summary`. A generated
workspace also lists its template-owned `docs/` pages, one line each, under "Project docs". This
module holds what the readers of that file share: which files are pages, which group a page
belongs to, how a page's line is derived from its text, and how a line is parsed, replaced and
inserted. Wiki lint checks the lines, the board service writes them, and `wiki search` reads them.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from prism_cli.wiki_model import parse_markdown_text
from prism_cli.wiki_paths import decoded_link_path


INDEX_FILE = "index.md"
STATUS_BOARD_FILE = "status-board.md"
# Files in the wiki root that are not pages: the index itself, the ledger and the generated report.
NON_PAGE_ROOT_FILES = frozenset({"index.md", "log.md", "WIKI_REPORT.md"})
# A generated workspace's `docs/` folder sits two levels above the wiki. Its pages are listed in the
# index by this prefix; they are project docs, not wiki pages.
PROJECT_DOCS_PREFIX = "../../docs/"
# The wiki folders that hold pages, one level deep.
PAGE_DIRECTORIES = (
    "features",
    "personas",
    "business-rules",
    "design",
    "technical-design",
    "app-requirements",
    "api-contracts",
    "decisions",
    "advisory",
    "topics",
    "research",
    "plans",
)
# Page kinds with no `_FORMAT.md` folder: single pages in the wiki root.
ROOT_PAGE_KINDS = {"direction.md": "direction", "roadmap.md": "roadmap"}
# Pages that state what is true now. Decisions and advisory reviews are records; the index, the log,
# the status board and the generated report are service-maintained views. Freshness and evidence
# labels apply to current-state pages only.
CURRENT_STATE_DIRECTORIES = frozenset(
    {
        "api-contracts",
        "app-requirements",
        "business-rules",
        "design",
        "features",
        "personas",
        "technical-design",
        "topics",
        "research",
        "plans",
        *ROOT_PAGE_KINDS,
    }
)
# The folders whose pages carry a `kind` front matter field, and the kind each one holds.
GENERAL_PAGE_FOLDERS = {"topics": "topic", "research": "research", "plans": "plan"}
GENERAL_PAGE_KINDS = frozenset({*GENERAL_PAGE_FOLDERS.values(), *ROOT_PAGE_KINDS.values()})
# Allowed `status` values of the page kinds that have a status. Direction and roadmap have none.
GENERAL_PAGE_STATUSES = {
    "topic": ("draft", "current"),
    "research": ("open", "concluded"),
    "plan": ("proposed", "active", "paused", "done", "dropped"),
}
# The `##` sections each general page kind needs, in order.
GENERAL_PAGE_SECTIONS = {
    "topic": ("Summary", "Key points", "Related pages"),
    "research": ("Question", "Summary", "Findings", "Gaps"),
    "plan": ("Summary", "Goal", "Current status", "Next steps", "Blockers"),
    "direction": ("Summary", "Direction", "Principles"),
    "roadmap": ("Summary", "Next", "Later"),
}

# The index groups, in file order: (group key, `##` heading).
GROUPS = (
    ("direction", "Direction and roadmap"),
    ("plans", "Plans"),
    ("topics", "Topics"),
    ("research", "Research"),
    ("features", "Features"),
    ("personas", "Personas"),
    ("business-rules", "Business rules"),
    ("design", "Design"),
    ("technical-design", "Technical design"),
    ("app-requirements", "App requirements"),
    ("api-contracts", "API contracts"),
    ("decisions", "Decisions"),
    ("advisory", "Advisory"),
    ("project-docs", "Project docs"),
    ("meta", "Meta"),
)
GROUP_HEADINGS = dict(GROUPS)

_SECTION_BY_GROUP = {"personas": "Who they are", "business-rules": "Rule", "decisions": "Decision"}
# The pages the template ships and the board never writes carry a fixed line.
_FIXED_LINES = {
    "SCHEMA.md": ("SCHEMA.md", "Wiki conventions and operational rules."),
    "LIFECYCLE.md": ("LIFECYCLE.md", "Feature, board and advisory protocol."),
    "CONNECTED.md": ("CONNECTED.md", "How agents use the connected board and MCP service."),
    "SETTINGS.md": ("SETTINGS.md", "Project-level settings for wiki read and query behavior."),
    "status-board.md": ("Status board", "The status, owner and board review of every feature."),
    "advisory/BOARD.md": ("Advisory board", "Advisory board composition."),
    "advisory/PROJECT_FOUNDATION.md": ("Project foundation", "Setup interview answers, risk framing and the initial board rationale."),
}
_SUMMARY_LIMIT = 200

# The text above the first group of `index.md`, as the template ships it.
INDEX_HEADER = (
    "# Wiki index\n\n"
    "One line per wiki page, grouped by kind. This file is maintained by the AI agent and the\n"
    "board service. Do not edit it directly.\n\n"
)

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_LIST_LINK = re.compile(r"^\s*[-*+]\s+\[[^\]]*\]\(\s*(?:<([^>]+)>|([^)\s]+))")
_PARENTHESIZED_LINK = re.compile(r"\s*\(\[[^\]]*\]\([^)]*\)\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EVIDENCE_PREFIX = re.compile(r"^\*\*[^*:]+:\*\*\s*")
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?")


def is_page_path(relative: str) -> bool:
    """Whether a wiki-relative path (`features/F-001-x.md`, `SCHEMA.md`) is a wiki page the index lists.

    Pages sit in the wiki root or one folder deep in a page folder; `_FORMAT.md` files, the index,
    the log and the generated report are not pages.
    """

    parts = PurePosixPath(relative).parts
    if not parts or not parts[-1].lower().endswith(".md") or parts[-1].startswith("_"):
        return False
    if len(parts) == 1:
        return parts[0] not in NON_PAGE_ROOT_FILES
    return len(parts) == 2 and parts[0] in PAGE_DIRECTORIES


def is_current_state_page(relative: str) -> bool:
    """Whether a wiki-relative path is a current-state page: a page that states what is true now.

    A record (a decision or an advisory review), the index, the log, the status board, the root
    schema files and the generated report are not.
    """

    parts = PurePosixPath(relative).parts
    if not is_page_path(relative):
        return False
    if len(parts) == 1:
        return parts[0] in ROOT_PAGE_KINDS
    return parts[0] in CURRENT_STATE_DIRECTORIES


def is_project_doc_target(target: str) -> bool:
    """Whether an index target (`../../docs/architecture.md`) names a Markdown page of the workspace `docs/` folder."""

    rest = target[len(PROJECT_DOCS_PREFIX) :] if target.startswith(PROJECT_DOCS_PREFIX) else ""
    return bool(rest) and rest.lower().endswith(".md") and ".." not in PurePosixPath(rest).parts


def page_group(relative: str) -> str | None:
    """The index group of a page or a project doc, or ``None`` when the path is neither."""

    if is_project_doc_target(relative):
        return "project-docs"
    if not is_page_path(relative):
        return None
    parts = PurePosixPath(relative).parts
    if len(parts) == 2:
        return parts[0]
    return "direction" if parts[0] in ROOT_PAGE_KINDS else "meta"


def general_page_kind(relative: str) -> str | None:
    """The kind of a topic, research, plan, direction or roadmap page, from its wiki-relative path."""

    parts = PurePosixPath(relative).parts
    if len(parts) == 2 and parts[0] in GENERAL_PAGE_FOLDERS and is_page_path(relative):
        return GENERAL_PAGE_FOLDERS[parts[0]]
    if len(parts) == 1 and parts[0] in ROOT_PAGE_KINDS:
        return ROOT_PAGE_KINDS[parts[0]]
    return None


@dataclass(frozen=True)
class IndexEntry:
    """One index line: the wiki-relative path it links, the line without its ending, and its 1-based number."""

    target: str
    line: str
    number: int


def index_target(raw_target: str) -> str | None:
    """The wiki-relative path an index link names, or ``None`` for a link that leaves the wiki or is not a file path.

    The one link that may leave the wiki is a project doc, `../../docs/<page>.md`; it is returned as written.
    """

    try:
        parsed = urlsplit(unquote(raw_target))
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or not parsed.path or "\x00" in parsed.path:
        return None
    safe, _problem = decoded_link_path(parsed.path, percent_encoded=False)
    if safe is None:
        return None
    normalized = posixpath.normpath(safe)
    if is_project_doc_target(normalized):
        return normalized
    if normalized.startswith(("/", "..")) or normalized == ".":
        return None
    return normalized


def parse_index_entries(text: str) -> list[IndexEntry]:
    """The index lines of a file: list items whose first element is a link. Fenced code is not read."""

    entries: list[IndexEntry] = []
    in_fence = False
    for number, raw_line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _LIST_LINK.match(raw_line)
        if match is None:
            continue
        target = index_target(match.group(1) or match.group(2))
        if target is not None:
            entries.append(IndexEntry(target=target, line=raw_line.rstrip("\r\n"), number=number))
    return entries


def _section(body: str, heading: str) -> str:
    wanted = heading.strip().casefold()
    lines = body.splitlines()
    start: int | None = None
    for position, line in enumerate(lines):
        match = _HEADING.match(line.strip())
        if match and match.group(1).strip().casefold() == wanted:
            start = position + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for position in range(start, len(lines)):
        if _HEADING.match(lines[position].strip()):
            end = position
            break
    return "\n".join(lines[start:end])


def _first_sentence(section: str) -> str:
    """The first sentence of a section's first paragraph, as plain text on one line (empty when there is none)."""

    paragraph: list[str] = []
    in_fence = False
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or line.startswith(("<!--", "|", "#", ">")):
            if paragraph:
                break
            continue
        if not line:
            if paragraph:
                break
            continue
        paragraph.append(line)
    text = " ".join(paragraph)
    text = _LIST_MARKER.sub("", text)
    text = _EVIDENCE_PREFIX.sub("", text)
    text = _PARENTHESIZED_LINK.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    match = re.search(r"[.!?](?=\s|$)", text)
    if match:
        text = text[: match.end()]
    if len(text) > _SUMMARY_LIMIT:
        text = text[: _SUMMARY_LIMIT - 3].rstrip() + "..."
    return text


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _label_text(value: str) -> str:
    return value.replace("[", "(").replace("]", ")")


def index_label(relative: str, frontmatter: Mapping[str, Any]) -> str:
    """The text of a page's index link: its ID and title, a derived name for requirement, contract and review pages."""

    if relative in _FIXED_LINES:
        return _FIXED_LINES[relative][0]
    group = page_group(relative)
    stem = PurePosixPath(relative).stem
    feature_id = _clean(frontmatter.get("feature-id"))
    title = _clean(frontmatter.get("title")) or _clean(frontmatter.get("name"))
    identifier = _clean(frontmatter.get("id"))
    if group == "app-requirements" and feature_id:
        label = f"{feature_id} {_clean(frontmatter.get('app')) or stem}"
    elif group == "api-contracts" and feature_id:
        label = f"{feature_id} API contract"
    elif group == "advisory" and feature_id:
        label = f"{feature_id} board review"
    elif group == "direction":
        label = stem.capitalize()
    elif title and identifier:
        label = f"{identifier} {title}"
    else:
        label = title or identifier or stem
    return _label_text(label)


def index_summary(relative: str, frontmatter: Mapping[str, Any], body: str) -> str:
    """The one-sentence summary of a page's index line, derived from its own text."""

    if relative in _FIXED_LINES:
        return _FIXED_LINES[relative][1]
    group = page_group(relative)
    feature_id = _clean(frontmatter.get("feature-id"))
    if group == "app-requirements" and feature_id:
        app = _clean(frontmatter.get("app")) or PurePosixPath(relative).stem
        return f"Requirements of {feature_id} for the {app} app."
    if group == "api-contracts" and feature_id:
        return f"API contract of {feature_id}."
    if group == "advisory" and feature_id:
        return f"Board review of {feature_id}."
    successor = _clean(frontmatter.get("superseded-by"))
    if group == "decisions" and frontmatter.get("status") == "superseded" and successor:
        return f"{successor} supersedes this decision."
    section = _SECTION_BY_GROUP.get(group or "", "Summary")
    return _first_sentence(_section(body, section))


def index_line(relative: str, frontmatter: Mapping[str, Any], body: str) -> str:
    """The index line of the page at wiki-relative path ``relative``: `- [Label](path): Summary`."""

    link = f"[{index_label(relative, frontmatter)}]({relative})"
    summary = index_summary(relative, frontmatter, body)
    return f"- {link}: {summary}" if summary else f"- {link}"


# -- writing ----------------------------------------------------------------------------------------


def _line_ending(line: str, newline: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else newline


def _entry_positions(lines: list[str]) -> list[tuple[int, str]]:
    """(line position, target) of every index line, reading outside fenced code only."""

    found: list[tuple[int, str]] = []
    in_fence = False
    for position, raw in enumerate(lines):
        stripped = raw.rstrip("\r\n")
        if _FENCE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _LIST_LINK.match(stripped)
        if match is None:
            continue
        target = index_target(match.group(1) or match.group(2))
        if target is not None:
            found.append((position, target))
    return found


def _headings(lines: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    in_fence = False
    for position, raw in enumerate(lines):
        stripped = raw.rstrip("\r\n")
        if _FENCE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING.match(stripped)
        if match:
            found.setdefault(match.group(1).strip().casefold(), position)
    return found


def render_index_lines(content: str, after: Mapping[str, str]) -> str:
    """Return ``content`` with each page's line in ``after`` replaced in place, or inserted in its group when absent.

    ``after`` maps a wiki-relative page path to its new line. A new line goes under its group's `##`
    heading, ahead of the first line of that group whose path sorts after it; the heading is
    created, in group order, when the file has none. The result depends only on the content and on
    ``after``, so applying the same merge twice changes nothing more.
    """

    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines(keepends=True)
    for target in sorted(after, key=str.casefold):
        line = after[target]
        group = page_group(target)
        if group is None:
            raise ValueError(f"`{target}` is not a wiki page or a project doc.")
        positions = [position for position, found in _entry_positions(lines) if found == target]
        if positions:
            lines[positions[0]] = line + _line_ending(lines[positions[0]], newline)
            continue
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += newline
        heading_text = GROUP_HEADINGS[group]
        headings = _headings(lines)
        heading = headings.get(heading_text.casefold())
        if heading is None:
            later = [
                headings[GROUP_HEADINGS[key].casefold()]
                for key, _heading in GROUPS[[key for key, _ in GROUPS].index(group) + 1 :]
                if GROUP_HEADINGS[key].casefold() in headings
            ]
            block = [f"## {heading_text}{newline}", line + newline]
            if later:
                lines[min(later) : min(later)] = [*block, newline]
            else:
                if lines and lines[-1].strip():
                    lines.append(newline)
                lines.extend(block)
            continue
        end = len(lines)
        for position in range(heading + 1, len(lines)):
            if _HEADING.match(lines[position].rstrip("\r\n")):
                end = position
                break
        members = [(position, found) for position, found in _entry_positions(lines) if heading < position < end]
        later_members = [position for position, found in members if found.casefold() > target.casefold()]
        if later_members:
            insertion = later_members[0]
        elif members:
            insertion = members[-1][0] + 1
        else:
            insertion = heading + 1
        lines.insert(insertion, line + newline)
    return "".join(lines)


def build_index(wiki_root: Path) -> str:
    """The text of `index.md` for the pages on disk under ``wiki_root``: one derived line per page, grouped by kind."""

    lines: dict[str, str] = {}
    for path in sorted(wiki_root.rglob("*.md"), key=lambda item: item.relative_to(wiki_root).as_posix()):
        relative = path.relative_to(wiki_root).as_posix()
        if is_page_path(relative):
            page = parse_markdown_text(path, path.read_text(encoding="utf-8-sig"))
            lines[relative] = index_line(relative, page.frontmatter, page.body)
    return render_index_lines(INDEX_HEADER, lines)


def remove_index_lines(content: str, targets: Iterable[str]) -> str:
    """Return ``content`` without the index lines of the given page paths (a heading left empty stays)."""

    wanted = set(targets)
    lines = content.splitlines(keepends=True)
    drop = {position for position, found in _entry_positions(lines) if found in wanted}
    return "".join(line for position, line in enumerate(lines) if position not in drop)
