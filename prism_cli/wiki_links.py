"""Shared wiki cross-reference helpers used by read/query and graph surfaces."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from prism_cli.wiki_model import FRONTMATTER_PATTERN, MARKDOWN_LINK_PATTERN


LINKED_CONTEXT_DIRECTORIES = {
    "design": "design",
    "api_contracts": "api-contracts",
    "advisory_reviews": "advisory",
    "business_rules": "business-rules",
    "personas": "personas",
    "decisions": "decisions",
}

NON_PAGE_FILENAMES = {
    "BOARD.md",
    "PROJECT_FOUNDATION.md",
    "_FORMAT.md",
    "SCHEMA.md",
    "LIFECYCLE.md",
    "SETTINGS.md",
    "index.md",
    "status-board.md",
    "log.md",
    "WIKI_REPORT.md",
}


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
    from prism_cli.wiki_model import load_markdown_page

    linked_context: dict[str, list[str]] = {key: [] for key in LINKED_CONTEXT_DIRECTORIES}
    for context_key, directory in LINKED_CONTEXT_DIRECTORIES.items():
        for path in markdown_files(wiki_root / directory):
            if path.name in NON_PAGE_FILENAMES:
                continue
            page = load_markdown_page(path)
            if page_references_feature(page.frontmatter, page.body, path.name, feature_id):
                linked_context[context_key].append(str(path))
    return linked_context


# `repo:<repository-id>/<path>` links a file or folder in an app's external repository.
EXTERNAL_LINK_PREFIX = "repo:"

_FENCE_LINE = re.compile(r"^\s*(?:```|~~~)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(?P<text>.*?)(?:[ \t]+#+)?[ \t]*$")
_HTML_ANCHOR = re.compile(r"""<a\s[^>]*?\b(?:id|name)=["']([^"']+)["']""", re.IGNORECASE)
_MARKDOWN_TEXT_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def iter_markdown_links(text: str) -> Iterator[tuple[int, str]]:
    """Yield `(line number, target)` for each inline Markdown link outside code, in text order.

    Images, reference-style links, fenced code blocks and inline code are skipped. The target is
    returned as written; the caller splits off a fragment and decodes percent escapes.
    """

    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if _FENCE_LINE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in MARKDOWN_LINK_PATTERN.finditer(_INLINE_CODE.sub("", line)):
            yield number, match.group(1) or match.group(2)


def parse_external_link(target: str) -> tuple[str, str, str | None] | None:
    """Split a `repo:<repository-id>/<path>` link into `(repository id, path, problem)`.

    Returns ``None`` when the target is not a `repo:` link. A `repo:` link that is not well formed
    comes back with a one-sentence ``problem``. A `#fragment` is dropped: lint checks that the
    target exists and never reads a file in an external checkout.
    """

    if not target.startswith(EXTERNAL_LINK_PREFIX):
        return None
    body = target[len(EXTERNAL_LINK_PREFIX):].split("#", 1)[0].split("?", 1)[0]
    repository, _, path = body.partition("/")
    form = "`repo:<repository-id>/<path>`"
    if not repository:
        return "", path, f"it needs a repository id; the form is {form}."
    parts = PurePosixPath(path).parts
    if not path or "\\" in path or PurePosixPath(path).is_absolute() or any(part in {"", ".", ".."} for part in parts):
        return repository, path, f"it needs a path inside the repository, without `..`; the form is {form}."
    return repository, path, None


def heading_anchors(text: str) -> set[str]:
    """The anchors a Markdown page offers: its headings as GitHub names them, and explicit HTML anchors.

    A repeated heading gets `-1`, `-2` and so on, like GitHub. Front matter and fenced code are skipped.
    """

    match = FRONTMATTER_PATTERN.match(text)
    body = match.group(2) if match else text
    anchors: set[str] = set(_HTML_ANCHOR.findall(body))
    seen: dict[str, int] = {}
    in_fence = False
    for line in body.splitlines():
        if _FENCE_LINE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _ATX_HEADING.match(line)
        if heading is None:
            continue
        slug = _heading_slug(heading.group("text"))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def _heading_slug(text: str) -> str:
    plain = _MARKDOWN_TEXT_LINK.sub(r"\1", text).replace("`", "").replace("*", "")
    return re.sub(r"[^\w\- ]", "", plain.strip().lower()).replace(" ", "-")
