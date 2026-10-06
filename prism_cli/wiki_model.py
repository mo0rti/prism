"""Typed-ish readers for Prism wiki markdown files."""

from __future__ import annotations

import copy
import functools
import hashlib
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator
from urllib.parse import unquote, urlsplit

import yaml


VALID_FEATURE_STATUSES = {"raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "done"}
VALID_FEATURE_OWNERS = {"po", "designer", "dev", "none"}
VALID_OPEN_QUESTION_OWNERS = {"po", "designer", "dev"}
VALID_ADVISORY_REVIEW_STATES = {"not-needed", "pending", "done", "skipped"}
VALID_APP_REQUIREMENT_STATUSES = {"pending", "in-progress", "done"}
DEFAULT_WIKI_STALE_AFTER_DAYS = 14
REVALIDATION_DOMAINS = {
    "specification",
    "design",
    "implementation",
    "tests",
    "release",
}
DELIVERY_EVIDENCE_COLUMNS = ("app", "implementation", "tests", "release")


def _refuse_change(self: Any, *args: Any, **kwargs: Any) -> Any:
    raise TypeError(
        "A parsed wiki page is a read-only snapshot shared within one request; "
        "copy its mappings and lists (`dict(...)`, `list(...)`) before changing them."
    )


class FrozenDict(dict):
    """A ``dict`` that refuses in-place changes.

    It still compares, iterates and serializes like a ``dict``; copying it
    (``dict(x)``, ``copy.copy``, ``copy.deepcopy``) yields ordinary mutable objects.
    """

    __slots__ = ()
    __setitem__ = __delitem__ = __ior__ = _refuse_change
    clear = pop = popitem = setdefault = update = _refuse_change

    def __copy__(self) -> dict[Any, Any]:
        return dict(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        memo[id(self)] = result
        for key, value in self.items():
            result[copy.deepcopy(key, memo)] = copy.deepcopy(value, memo)
        return result

    def __reduce__(self) -> tuple[Any, ...]:
        return (dict, (dict(self),))


class FrozenList(list):
    """A ``list`` that refuses in-place changes; copying it yields an ordinary list."""

    __slots__ = ()
    __setitem__ = __delitem__ = __iadd__ = __imul__ = _refuse_change
    append = extend = insert = remove = pop = clear = sort = reverse = _refuse_change

    def __copy__(self) -> list[Any]:
        return list(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> list[Any]:
        result: list[Any] = []
        memo[id(self)] = result
        result.extend(copy.deepcopy(item, memo) for item in self)
        return result

    def __reduce__(self) -> tuple[Any, ...]:
        return (list, (list(self),))


def freeze(value: Any, _memo: dict[int, Any] | None = None) -> Any:
    """Return ``value`` with every nested ``dict`` and ``list`` made read-only.

    Containers that are already read-only are returned as they are. Parsed YAML
    may contain anchors that refer back to their own container, so the walk
    remembers what it has already converted.
    """

    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, dict):
        memo = {} if _memo is None else _memo
        if id(value) in memo:
            return memo[id(value)]
        frozen_dict = FrozenDict()
        memo[id(value)] = frozen_dict
        dict.update(frozen_dict, [(freeze(key, memo), freeze(item, memo)) for key, item in value.items()])
        return frozen_dict
    if isinstance(value, list):
        memo = {} if _memo is None else _memo
        if id(value) in memo:
            return memo[id(value)]
        frozen_list = FrozenList()
        memo[id(value)] = frozen_list
        list.extend(frozen_list, [freeze(item, memo) for item in value])
        return frozen_list
    return value


@dataclass(frozen=True)
class MarkdownPage:
    """One parsed wiki page.

    Pages are shared between the readers of a request (see ``wiki_read_scope``),
    so ``frontmatter`` and ``parse_errors`` are read-only; copy before changing.
    """

    path: Path
    frontmatter: dict[str, Any]
    body: str
    parse_errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "frontmatter", freeze(self.frontmatter))
        object.__setattr__(self, "parse_errors", freeze(self.parse_errors))


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
    def apps(self) -> list[str]:
        value = self.page.frontmatter.get("apps")
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]


@dataclass(frozen=True)
class AppRequirementPage:
    page: MarkdownPage

    @property
    def feature_id(self) -> str | None:
        value = self.page.frontmatter.get("feature-id")
        return value if isinstance(value, str) else None

    @property
    def app(self) -> str | None:
        value = self.page.frontmatter.get("app")
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
    """Read and parse one markdown page, always from the file."""

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return _unreadable_page(path, exc)
    return parse_markdown_text(path, text)


def _unreadable_page(path: Path, exc: BaseException) -> MarkdownPage:
    return MarkdownPage(path=path, frontmatter={}, body="", parse_errors=[f"Unable to read file: {exc}"])


def parse_markdown_text(path: Path, text: str) -> MarkdownPage:
    """Parse the text of the page at ``path``."""

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


class WikiPageScope:
    """Parsed pages shared by every reader of one request.

    A request (a preview, a query, a graph build, an apply) opens one scope with
    ``wiki_read_scope`` and drops it when it ends, so nothing survives between
    requests and the board's stale-change detection is unchanged. Inside the
    scope ``load_markdown_page`` parses a page once:

    * A page whose file still has the ``(mtime, size, inode, ctime, device)`` it
      had when it was read is reused without opening the file, but only when the
      file was already older than ``RACY_WINDOW_NS`` at that read, so a later
      write is bound to change the modification time. The window is the one the
      change poller's ``FingerprintCache`` uses.
    * Any other page is read from the file again and compared with the cached
      one by the SHA-256 digest of its text. An equal digest reuses the parsed
      page; a different one parses the new text. A page rewritten with the same
      size inside one timestamp tick is therefore never served stale.
    """

    RACY_WINDOW_NS = 2_000_000_000

    def __init__(self, *, wall_clock_ns: Callable[[], int] = time.time_ns) -> None:
        self._wall_clock_ns = wall_clock_ns
        # path -> (stat signature, text digest, page, reusable without rereading the file)
        self._entries: dict[str, tuple[tuple[int, ...], bytes, MarkdownPage, bool]] = {}
        # Facts other readers compute once per request, such as the workspace model.
        self.facts: dict[Any, Any] = {}

    def load(self, path: Path) -> MarkdownPage:
        read_started_ns = self._wall_clock_ns()
        try:
            info = path.stat()
        except (OSError, RuntimeError, ValueError):
            return read_markdown_page(path)
        signature = (info.st_mtime_ns, info.st_size, info.st_ino, info.st_ctime_ns, info.st_dev)
        key = str(path)
        entry = self._entries.get(key)
        if entry is not None and entry[3] and entry[0] == signature:
            return entry[2]
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            self._entries.pop(key, None)
            return _unreadable_page(path, exc)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        page = entry[2] if entry is not None and entry[1] == digest else parse_markdown_text(path, text)
        settled = read_started_ns - info.st_mtime_ns > self.RACY_WINDOW_NS
        self._entries[key] = (signature, digest, page, settled)
        return page


_PAGE_SCOPE: ContextVar[WikiPageScope | None] = ContextVar("prism_wiki_page_scope", default=None)


@contextmanager
def wiki_read_scope() -> Iterator[WikiPageScope]:
    """Share parsed pages between the readers of one request.

    The outermost caller owns the scope and a nested call joins it. Wrap exactly
    one request in it, never work that outlives the request.
    """

    current = _PAGE_SCOPE.get()
    if current is not None:
        yield current
        return
    scope = WikiPageScope()
    token = _PAGE_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _PAGE_SCOPE.reset(token)


def within_wiki_read_scope(function: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: run ``function`` inside ``wiki_read_scope``, joining one that is already open."""

    @functools.wraps(function)
    def scoped(*args: Any, **kwargs: Any) -> Any:
        with wiki_read_scope():
            return function(*args, **kwargs)

    return scoped


def request_fact(key: Any, compute: Callable[[], Any]) -> Any:
    """Return a fact computed once per ``wiki_read_scope``; outside a scope it is computed every time."""

    scope = _PAGE_SCOPE.get()
    if scope is None:
        return compute()
    if key not in scope.facts:
        scope.facts[key] = compute()
    return scope.facts[key]


def load_markdown_page(path: Path) -> MarkdownPage:
    """Return the page at ``path``: shared inside a ``wiki_read_scope``, read from the file otherwise."""

    scope = _PAGE_SCOPE.get()
    if scope is None:
        return read_markdown_page(path)
    return scope.load(path)


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

    page = load_markdown_page(settings_path)
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
        FeaturePage(load_markdown_page(path))
        for path in sorted(features_dir.glob("*.md"))
        if not path.name.startswith("_")
    ]


def read_app_requirement_pages(wiki_root: Path) -> list[AppRequirementPage]:
    requirements_dir = wiki_root / "app-requirements"
    if not requirements_dir.exists():
        return []
    return [
        AppRequirementPage(load_markdown_page(path))
        for path in sorted(requirements_dir.glob("*.md"))
        if not path.name.startswith("_")
    ]


def read_markdown_pages(directory: Path) -> list[MarkdownPage]:
    """Read non-template markdown pages in a directory in stable path order."""

    if not directory.exists():
        return []
    return [
        load_markdown_page(path)
        for path in sorted(directory.glob("*.md"), key=lambda item: item.name)
        if not path.name.startswith("_")
    ]


def read_wiki_pages(wiki_root: Path) -> list[MarkdownPage]:
    """Read all markdown pages below a wiki root, including top-level index pages."""

    if not wiki_root.exists():
        return []
    return [
        load_markdown_page(path)
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


_NO_API_SURFACE = frozenset(
    {"none", "no api", "not applicable", "n/a", "no api changes", "no api changes identified", "no api changes required", "no api surface"}
)


def api_surface_declared(section: str) -> bool:
    """Whether a feature's `## API surface` text declares API work.

    An empty section and a plain statement that there is none (case, spacing and
    a closing period do not matter) declare nothing. Any other text needs an API
    contract page.
    """

    normalized = re.sub(r"\s+", " ", section).strip().lower().rstrip(".").strip()
    return bool(normalized) and normalized not in _NO_API_SURFACE


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
    declared_apps: list[str],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Parse the canonical per-app delivery evidence table.

    This validates only observable structure and substantive cells.  It does
    not claim that referenced implementation, test, or release artifacts exist;
    the responsible agent must verify those references before writing Done.
    """

    rows, _cells, errors = parse_delivery_evidence_cells(body, declared_apps)
    return rows, errors


def parse_delivery_evidence_cells(
    body: str,
    declared_apps: list[str],
) -> tuple[dict[str, dict[str, str]], dict[str, list[str]], list[str]]:
    """Parse the delivery evidence table like ``parse_delivery_evidence``.

    The second mapping holds each app's cells exactly as written, in the
    table's own column order, so a caller can archive a row verbatim whatever
    column order the table uses.  App keys are lower case in both mappings.
    """

    section = section_text(body, "Delivery evidence")
    if not section.strip():
        return {}, {}, ["Required `Delivery evidence` section is missing or empty."]

    table_lines = _visible_evidence_table_lines(section)
    if not table_lines:
        return {}, {}, ["Delivery evidence must contain a markdown table."]

    header: list[str] | None = None
    header_indexes: dict[str, int] = {}
    rows: dict[str, dict[str, str]] = {}
    written: dict[str, list[str]] = {}
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
            errors.append("Delivery evidence table is missing the App/Implementation/Tests/Release header.")
            continue
        if len(normalized) == len(DELIVERY_EVIDENCE_COLUMNS) and set(normalized) == set(DELIVERY_EVIDENCE_COLUMNS):
            errors.append("Delivery evidence contains more than one header/table.")
            continue
        if _is_separator_row(cells):
            continue
        if len(cells) != len(DELIVERY_EVIDENCE_COLUMNS):
            errors.append("Delivery evidence table rows must contain exactly App, Implementation, Tests, and Release cells.")
            continue
        app_id = cells[header_indexes["app"]].strip().lower()
        if not app_id:
            errors.append("Every delivery evidence row must name an app.")
            continue
        if app_id in rows:
            errors.append(f"Delivery evidence contains duplicate app `{app_id}` rows.")
            continue
        row = {
            column: cells[index].strip()
            for column, index in header_indexes.items()
        }
        rows[app_id] = row
        written[app_id] = list(cells)
        for column in DELIVERY_EVIDENCE_COLUMNS[1:]:
            if not _substantive_evidence_cell(row[column]):
                errors.append(f"Delivery evidence `{column}` for `{app_id}` is empty or still a placeholder.")

    if header is None:
        errors.append("Delivery evidence table has no usable header row.")

    declared = {item.strip().lower() for item in declared_apps if isinstance(item, str) and item.strip()}
    missing = sorted(declared - set(rows))
    extra = sorted(set(rows) - declared)
    if missing:
        errors.append("Delivery evidence is missing declared app(s): " + ", ".join(missing) + ".")
    if extra:
        errors.append("Delivery evidence contains undeclared app(s): " + ", ".join(extra) + ".")
    return rows, written, errors


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


_SOURCE_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
PENDING_INTAKE_PREFIX = ("knowledge", "intake", "pending")


def source_link_parts(entry: Any, *, path_only: bool = True) -> tuple[str, ...] | None:
    """Return a `sources` entry as workspace path segments, or None when it is not a workspace path.

    A URL, an absolute or parent-relative path and a blank entry are not
    workspace links. `intake/...` is read as `knowledge/intake/...`. With
    `path_only=False`, which personas and business rules use because their
    source fields may hold free text, only an entry that already starts with
    `knowledge/` counts as a link.
    """

    if not isinstance(entry, str):
        return None
    text = entry.strip()
    if not text or _SOURCE_SCHEME.match(text):
        return None
    if not path_only and re.search(r"\s", text):
        return None
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    parts = path.parts
    if parts[0].casefold() == "intake":
        parts = ("knowledge", *parts)
    if not path_only and parts[0].casefold() != "knowledge":
        return None
    return parts


def is_pending_intake_source(parts: tuple[str, ...]) -> bool:
    """Whether workspace path segments lie in the pending intake queue."""

    return len(parts) >= 3 and tuple(part.casefold() for part in parts[:3]) == PENDING_INTAKE_PREFIX


def processed_source_path(parts: tuple[str, ...]) -> str:
    """The `knowledge/intake/processed/<folder>` path that replaces a pending source path."""

    return "/".join(("knowledge", "intake", "processed", *(parts[3:] or ("<folder>",))))


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
