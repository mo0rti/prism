"""Typed-ish readers for Prism wiki markdown files."""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import re
import time
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Mapping
from urllib.parse import unquote, urlsplit

import yaml

from prism_cli.app_model import CAPABILITY_HAS_UI, DELIVERY_KINDS, STACKS, WorkspaceModel
from prism_cli.wiki_paths import resolve_to_path


# The feature lifecycle in order (CONTRACTS 2.1). A feature before `in-dev` is moved by the actions; from `in-dev` on its
# status is the minimum of its app stages.
FEATURE_STATUS_ORDER = (
    "raw",
    "specified",
    "ready-for-design",
    "in-design",
    "ready-for-dev",
    "in-dev",
    "ready-for-qa",
    "in-qa",
    "ready-for-release",
    "released",
)
VALID_FEATURE_STATUSES = set(FEATURE_STATUS_ORDER)
VALID_FEATURE_OWNERS = {"po", "designer", "tech-lead", "dev", "qa", "release", "none"}
VALID_OPEN_QUESTION_OWNERS = {"po", "designer", "tech-lead", "dev", "qa", "release"}
VALID_ADVISORY_REVIEW_STATES = {"not-needed", "pending", "done", "skipped"}
VALID_APP_REQUIREMENT_STATUSES = {"pending", "in-progress", "done"}
DEFAULT_WIKI_STALE_AFTER_DAYS = 14
# The app stages, in order, and the owner of a feature at each status that has one owner.
APP_STAGE_ORDER = ("in-dev", "ready-for-qa", "in-qa", "ready-for-release", "released")
DESIGN_STATUSES = ("ready-for-design", "in-design")
DESIGN_OWNERS = ("designer", "tech-lead")
OWNER_BY_STATUS = {
    "raw": "po",
    "specified": "po",
    "ready-for-dev": "dev",
    "in-dev": "dev",
    "ready-for-qa": "qa",
    "in-qa": "qa",
    "ready-for-release": "release",
    "released": "none",
}
# The feature-level revalidation domains and the per-app ones (CONTRACTS 2.6), each in canonical order.
FEATURE_REVALIDATION_DOMAINS = ("specification", "design", "technical-design")
APP_REVALIDATION_DOMAINS = ("implementation", "tests", "qa", "release")
REVALIDATION_DOMAINS = set(FEATURE_REVALIDATION_DOMAINS)
# The front matter keys a feature page may carry (CONTRACTS 6.1). Any other key is `unsupported-feature-field`.
FEATURE_FRONTMATTER_FIELDS = (
    "id",
    "title",
    "status",
    "owner",
    "apps",
    "sources",
    "advisory-review",
    "advisory-skip-reason",
    "criteria-high-water",
    "design-tracks",
    "design-reaffirm",
    "revalidation",
    "app-revalidation",
)
FEATURE_SECTIONS = (
    "Summary",
    "User story",
    "Acceptance criteria",
    "Open questions",
    "App scope",
    "Design",
    "Related features",
    "API surface",
    "Board review summary",
    "Delivery evidence",
    "QA verification",
    "Release",
    "Evidence history",
)
# The five sections `po-intake` writes; `po-specify` adds the rest.
INTAKE_SECTIONS = ("Summary", "User story", "Acceptance criteria", "Open questions", "App scope")
EVIDENCE_SECTIONS = ("Delivery evidence", "QA verification", "Release")
DELIVERY_EVIDENCE_COLUMNS = ("app", "artifact", "contract", "implementation", "tests", "basis")
QA_VERIFICATION_COLUMNS = ("row", "criteria", "method", "artifact", "environment", "attempt", "result", "evidence", "basis")
RELEASE_COLUMNS = ("app", "target", "version", "attempt", "outcome", "record", "basis")


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
    # The number of file lines above the body, so a line of the body maps to a line of the file.
    body_offset: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "frontmatter", freeze(self.frontmatter))
        object.__setattr__(self, "parse_errors", freeze(self.parse_errors))


@dataclass(frozen=True)
class WikiSettings:
    """Read-only settings shared by wiki lint and other read surfaces.

    Besides the staleness setting it carries the workflow policy: `qa_separate_from_dev` and the resolved delivery
    targets (CONTRACTS 1.6 and 7). A malformed policy value is reported in `policy_errors` and is never read as the
    default; a gated action that reads the policy is refused while `policy_errors` is not empty.
    """

    stale_after_days: int
    path: Path
    used_fallback: bool = False
    diagnostics: tuple[tuple[str, str], ...] = ()
    qa_separate_from_dev: bool = False
    # app ID -> {"kind", "target", "environments"}; an app with no declared target and no stack default is absent.
    delivery_targets: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    # (code, message) pairs: `invalid-workflow-policy` and `invalid-delivery-target`, each an error.
    policy_errors: tuple[tuple[str, str], ...] = ()

    @property
    def policy_valid(self) -> bool:
        return not self.policy_errors

    @property
    def policy(self) -> dict[str, Any]:
        """The workflow policy as plain JSON values: the separation key and the resolved delivery targets."""

        return {
            "qa_separate_from_dev": self.qa_separate_from_dev,
            "delivery_targets": {
                app_id: {"kind": entry["kind"], "target": entry["target"], "environments": list(entry["environments"])}
                for app_id, entry in sorted(self.delivery_targets.items())
            },
        }

    @property
    def policy_revision(self) -> str:
        """`sha256` of the canonical JSON of the policy."""

        return hashlib.sha256(canonical_json(self.policy).encode("utf-8")).hexdigest()


def workflow_policy(wiki_root: Path, model: "WorkspaceModel | None" = None) -> dict[str, Any]:
    """The workflow policy of a workspace and the resolution of its delivery targets, in one call (CONTRACTS 1.6, 7).

    Returns `qa_separate_from_dev` (``False`` when the key is absent or malformed), `delivery_targets` (app ID -> kind, target,
    environments), `revision` (the SHA-256 of the canonical JSON of the policy), `valid` and `errors`, a list of
    `{code, message}` for a malformed value. A caller that gates an action refuses it with `invalid_policy` while `valid`
    is false: a malformed value is never read as `false`.
    """

    settings = read_wiki_settings(wiki_root, model)
    return {
        **settings.policy,
        "revision": settings.policy_revision,
        "valid": settings.policy_valid,
        "errors": [{"code": code, "message": message} for code, message in settings.policy_errors],
    }


def canonical_json(value: Any) -> str:
    """The canonical JSON text of a value: sorted keys, no spaces, non-ASCII escaped."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


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
class StatusBoardRow:
    feature_id: str
    title: str
    status: str
    owner: str
    advisory_review: str
    path: Path
    # The columns D5 fills in (`Design tracks`, `Open bugs`) carry `—` until then and are not compared with the pages.
    design_tracks: str = "—"
    app_stages: str = "—"
    open_bugs: str = "—"


# The header of the feature table of `status-board.md` (CONTRACTS 8.2), exact and in this order.
STATUS_BOARD_COLUMNS = ("ID", "Feature", "Status", "Owner", "Board Review", "Design tracks", "App stages", "Open bugs")


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
    offset = text.count("\n", 0, match.start(2))
    try:
        loaded = yaml.safe_load(raw_frontmatter) or {}
    except (yaml.YAMLError, TypeError, ValueError, OverflowError) as exc:
        return MarkdownPage(path=path, frontmatter={}, body=body, parse_errors=[f"Invalid YAML frontmatter: {exc}"], body_offset=offset)

    if not isinstance(loaded, dict):
        return MarkdownPage(path=path, frontmatter={}, body=body, parse_errors=["YAML frontmatter must be a mapping."], body_offset=offset)

    return MarkdownPage(path=path, frontmatter=loaded, body=body, body_offset=offset)


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


_DELIVERY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_DELIVERY_ENTRY_KEYS = frozenset({"kind", "target", "environments"})


def resolve_delivery_targets(
    declared: Any,
    model: "WorkspaceModel | None",
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """The delivery target of each app of the workspace, and the problems with the declared ones (CONTRACTS 7).

    `declared` is the `delivery-targets` mapping of `SETTINGS.md`, or ``None``. An entry may name a `kind`, a `target` and
    `environments`; what it leaves out comes from the app's stack default. An app with neither a declared nor a default
    kind and target has no entry (an app of the `other` stack must declare one before a release). Without a model only the
    declared entries are checked and resolved.
    """

    problems: list[tuple[str, str]] = []
    entries: dict[str, Mapping[str, Any]] = {}
    if declared is None:
        pass
    elif not isinstance(declared, Mapping):
        problems.append(("invalid-delivery-target", "`delivery-targets` must map app IDs to {kind, target, environments}."))
    else:
        for app_id, entry in declared.items():
            if not isinstance(app_id, str) or (model is not None and model.app(app_id) is None):
                problems.append(("invalid-delivery-target", f"`delivery-targets` names `{app_id}`, which is not an app of this workspace."))
                continue
            if not isinstance(entry, Mapping) or set(entry) - _DELIVERY_ENTRY_KEYS:
                problems.append(("invalid-delivery-target", f"The delivery target of `{app_id}` must be a mapping with only `kind`, `target` and `environments`."))
                continue
            kind = entry.get("kind")
            if kind is not None and kind not in DELIVERY_KINDS:
                problems.append(("invalid-delivery-target", f"The delivery kind of `{app_id}` must be one of {', '.join(DELIVERY_KINDS)}."))
                continue
            target = entry.get("target")
            if target is not None and (not isinstance(target, str) or not _DELIVERY_NAME.match(target)):
                problems.append(("invalid-delivery-target", f"The delivery target of `{app_id}` must be a short name such as `production`."))
                continue
            environments = entry.get("environments", [])
            if (
                not isinstance(environments, list)
                or any(not isinstance(item, str) or not _DELIVERY_NAME.match(item) for item in environments)
                or len(set(environments)) != len(environments)
            ):
                problems.append(("invalid-delivery-target", f"The environments of `{app_id}` must be a list of distinct short names."))
                continue
            entries[app_id] = entry
    resolved: dict[str, dict[str, Any]] = {}
    app_ids = [app.id for app in model.apps] if model is not None else list(entries)
    for app_id in app_ids:
        entry = entries.get(app_id, {})
        app = model.app(app_id) if model is not None else None
        stack = STACKS.get(app.stack) if app is not None else None
        kind = entry.get("kind") or (stack.delivery_kind if stack is not None else None)
        target = entry.get("target") or (stack.delivery_target if stack is not None else None)
        if kind is None or target is None:
            continue
        resolved[app_id] = {"kind": kind, "target": target, "environments": list(entry.get("environments", []))}
    return resolved, problems


def _workflow_policy(
    frontmatter: Mapping[str, Any],
    model: "WorkspaceModel | None",
) -> dict[str, Any]:
    """The policy keyword arguments of `WikiSettings` for a SETTINGS front matter."""

    errors: list[tuple[str, str]] = []
    separate = False
    if "qa-separate-from-dev" in frontmatter:
        value = frontmatter["qa-separate-from-dev"]
        if isinstance(value, bool):
            separate = value
        else:
            errors.append(("invalid-workflow-policy", "`qa-separate-from-dev` must be `true` or `false`."))
    targets, problems = resolve_delivery_targets(frontmatter.get("delivery-targets"), model)
    errors.extend(problems)
    return {"qa_separate_from_dev": separate, "delivery_targets": targets, "policy_errors": tuple(errors)}


def read_wiki_settings(wiki_root: Path, model: "WorkspaceModel | None" = None) -> WikiSettings:
    """Read the canonical `wiki-stale-after-days` setting with its documented fallback, and the workflow policy.

    `model` is the workspace model: with it the delivery targets resolve to the stack defaults of every app. A malformed
    policy value is returned in `policy_errors`; it is never read as `false`.
    """

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
            **_workflow_policy({}, model),
        )

    page = load_markdown_page(settings_path)
    if page.parse_errors:
        return WikiSettings(
            stale_after_days=DEFAULT_WIKI_STALE_AFTER_DAYS,
            path=settings_path,
            used_fallback=True,
            diagnostics=tuple(("invalid-wiki-settings", message) for message in page.parse_errors),
            **_workflow_policy({}, model),
        )

    policy = _workflow_policy(page.frontmatter, model)
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
            **policy,
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
            **policy,
        )
    return WikiSettings(stale_after_days=parsed, path=settings_path, **policy)


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


def candidate_relative_markdown_link(source_path: Path, raw_target: str, boundary: Path) -> Path | None:
    """Resolve a relative Markdown path of a page to a file path below `boundary`, or ``None``.

    `raw_target` is a link target as `extract_markdown_links` returns it (already percent-decoded). The shared
    resolver (`prism_cli/wiki_paths.py`) refuses a UNC, rooted, drive-qualified or backslash path, a double-encoded
    one, a `..` escape and a path through a link before any filesystem call.
    """

    try:
        parsed = urlsplit(raw_target)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or not parsed.path.lower().endswith(".md"):
        return None
    try:
        base = source_path.parent.resolve()
        return resolve_to_path(boundary.resolve(), base, parsed.path, percent_encoded=False)
    except (OSError, RuntimeError, ValueError):
        return None


def resolve_relative_markdown_link(source_path: Path, raw_target: str, wiki_root: Path) -> Path | None:
    """Resolve a relative markdown target when it stays inside the wiki root."""
    return candidate_relative_markdown_link(source_path, raw_target, wiki_root)


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


RELEASE_EVIDENCE_REQUIRED = "release-evidence-required"

_RELEASE_EVIDENCE_FORM = re.compile(r"^(release|tag|deployment)\s*:\s*(.*)$", re.IGNORECASE)
_DELIVERY_ATTESTATION_FORM = re.compile(r"^attested\s+by\s+([^:]*?)\s*:\s*(.*)$", re.IGNORECASE)
_RELEASE_FORMS_HINT = (
    "Write `release: <URL or record path>`, `tag: <URL or record path>` or `deployment: <URL or record path>`, "
    "or `attested by <Name>: <URL or path to what they checked>`."
)
_SHIPPED_NOTICE = "A commit or pull request proves which code changed, not that it shipped."
_MARKDOWN_LINK_TARGET = re.compile(r"^\[[^\]]*\]\(\s*<?([^)\s>]+)>?\s*\)")
_HTTP_URL = re.compile(r"^https?://[^\s/?#]+", re.IGNORECASE)
# A pull request, merge request or commit page says what changed, never that it shipped.
_CODE_CHANGE_URL_SEGMENT = re.compile(
    r"^(?:pulls?|pull-requests?|pullrequests?|merge[_-]requests?|commits?)$", re.IGNORECASE
)
_COMMIT_SHA = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
_RECORD_FILE_EXTENSION = re.compile(r"\.(?:md|txt|json|ya?ml|html?|pdf|csv)$", re.IGNORECASE)


def release_evidence_problem(value: str) -> str | None:
    """Why a ``Release`` cell is not release evidence or a delivery attestation, or ``None`` when it is.

    A cell is one of two forms, matched case-insensitively on the prefix:

    * release evidence: ``release: <reference>``, ``tag: <reference>`` or
      ``deployment: <reference>``, where the reference is the URL of, or a
      workspace path to, a release, tag or deployment record. A pull request,
      merge request or commit link is not one;
    * a delivery attestation: ``attested by <Name>: <reference>``, where the
      reference is a URL or a workspace path to what the person checked.

    The reference is the first word after the prefix (a Markdown link counts by
    its target). Only the shape is checked; the responsible agent verifies that
    the record exists and contains the change.
    """

    text = re.sub(r"\s+", " ", value).strip()
    if not _substantive_evidence_cell(text):
        return "is empty or still a placeholder"
    attestation = _DELIVERY_ATTESTATION_FORM.match(text)
    if attestation:
        name, reference = attestation.groups()
        if not re.search(r"[^\W\d_]", name) or re.fullmatch(r"[<\[].*[>\]]", name):
            return "names no person after `attested by`"
        return _release_reference_problem(reference, allow_code_change=True)
    release = _RELEASE_EVIDENCE_FORM.match(text)
    if release:
        return _release_reference_problem(release.group(2), allow_code_change=False)
    return "does not start with `release:`, `tag:`, `deployment:` or `attested by <Name>:`"


def _release_reference_problem(reference: str, *, allow_code_change: bool) -> str | None:
    text = reference.strip()
    link = _MARKDOWN_LINK_TARGET.match(text)
    token = link.group(1) if link else (text.split(" ", 1)[0] if text else "")
    token = token.strip("`<>").rstrip(".,;")
    if not token or not _substantive_evidence_cell(token) or re.fullmatch(r"\[[^\]]*\]", token):
        return "has no reference after the prefix"
    if _HTTP_URL.match(token):
        if not allow_code_change:
            try:
                segments = [segment for segment in urlsplit(token).path.split("/") if segment]
            except ValueError:
                return "is not a valid URL"
            if any(_CODE_CHANGE_URL_SEGMENT.match(segment) for segment in segments):
                return "points to a commit or pull request, not to a release, tag or deployment record"
        return None
    if _COMMIT_SHA.match(token):
        return "is a commit SHA"
    if "://" in token or re.match(r"^[A-Za-z]:", token) or token.startswith(("/", "\\")) or "\\" in token:
        return "must be an http(s) URL or a path inside the workspace"
    parts = token.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "must be an http(s) URL or a path inside the workspace"
    if "/" not in token and not _RECORD_FILE_EXTENSION.search(token):
        return "is neither a URL nor a path to a record in the workspace"
    return None


def parse_app_revalidation(value: Any) -> tuple[dict[str, list[str]], list[str]]:
    """Parse the optional per-app revalidation mapping: app ID -> domains in `APP_REVALIDATION_DOMAINS`.

    Like `parse_revalidation` it is strict, so an unknown domain never makes an app look current.
    """

    if value is None:
        return {}, []
    if not isinstance(value, Mapping):
        return {}, ["`app-revalidation` must map app IDs to lists of lifecycle domains."]
    result: dict[str, list[str]] = {}
    errors: list[str] = []
    for app_id, domains in value.items():
        if not isinstance(app_id, str) or not app_id.strip():
            errors.append("Every `app-revalidation` key must be an app ID.")
            continue
        if not isinstance(domains, list):
            errors.append(f"`app-revalidation` for `{app_id}` must be a list of lifecycle domains.")
            continue
        seen: list[str] = []
        for item in domains:
            domain = item.strip().lower() if isinstance(item, str) else ""
            if domain not in APP_REVALIDATION_DOMAINS:
                errors.append(
                    f"`app-revalidation` for `{app_id}` contains unsupported domain `{item}`; expected one of {list(APP_REVALIDATION_DOMAINS)}."
                )
            elif domain in seen:
                errors.append(f"`app-revalidation` for `{app_id}` contains duplicate domain `{domain}`.")
            else:
                seen.append(domain)
        if seen:
            result[app_id] = seen
    return result, errors


def merge_revalidation(current: Iterable[str], added: Iterable[str], order: tuple[str, ...]) -> list[str]:
    """The domains of `current` and `added` together, in the canonical `order`."""

    wanted = {*current, *added}
    return [domain for domain in order if domain in wanted]


def design_owner(apps: Iterable[str], model: WorkspaceModel | None) -> str:
    """The design owner `D` of a scope (CONTRACTS 0): `designer` when an active app has `has-ui` true or `unknown`, otherwise `tech-lead`.

    Without a model every app counts as `unknown`, which is the stricter side, so the owner is `designer`.
    """

    if model is None:
        return "designer"
    for app_id in apps:
        app = model.app(app_id)
        if app is not None and app.active and app.gate_capability(CAPABILITY_HAS_UI):
            return "designer"
    return "tech-lead"


def expected_owner(status: str | None, apps: Iterable[str], model: WorkspaceModel | None) -> str | None:
    """The owner a feature has at `status` (CONTRACTS 2.1), or ``None`` for an unknown status."""

    if status in DESIGN_STATUSES:
        return design_owner(apps, model)
    return OWNER_BY_STATUS.get(status or "")


def status_rank(status: str | None) -> int:
    """The position of a feature status in the lifecycle, or -1 for an unknown one."""

    try:
        return FEATURE_STATUS_ORDER.index(status or "")
    except ValueError:
        return -1


# --- Evidence tables ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceProblem:
    """One reason an evidence table or row is not acceptable. `code` is the board error code of the problem."""

    code: str
    message: str
    # The app (or QA row key) the problem names, when it names one.
    subject: str | None = None


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _plain_header(cell: str) -> str:
    return re.sub(r"[*_`]+", "", cell).strip().lower()


def _row_text(cells: Iterable[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def parse_evidence_table(
    body: str,
    heading: str,
    columns: tuple[str, ...],
    code: str,
) -> tuple[list[tuple[str, ...]], list[EvidenceProblem]]:
    """The data rows of the table under `## heading`, as cell tuples, and the problems with its shape.

    A section with no text, or with text and no table, has no rows and no problem: an empty section is the state before
    the evidence exists. A table must start with the header `columns` (case, bold and backticks are ignored) and every
    row must have one cell per column. Lines inside code fences and HTML comments are not read.
    """

    section = section_text(body, heading)
    if not section.strip():
        return [], []
    lines = _visible_evidence_table_lines(section)
    if not lines:
        return [], []
    rows: list[tuple[str, ...]] = []
    problems: list[EvidenceProblem] = []
    header_seen = False
    for line in lines:
        cells = _split_table_row(line)
        if not header_seen:
            if _is_separator_row(cells):
                continue
            if tuple(_plain_header(cell) for cell in cells) != columns:
                names = " | ".join(column.capitalize() for column in columns)
                problems.append(EvidenceProblem(code, f"The `{heading}` table must start with the header `| {names} |`."))
                return [], problems
            header_seen = True
            continue
        if _is_separator_row(cells):
            continue
        if tuple(_plain_header(cell) for cell in cells) == columns:
            problems.append(EvidenceProblem(code, f"The `{heading}` section has more than one table header."))
            continue
        if len(cells) != len(columns):
            problems.append(EvidenceProblem(code, f"A row of the `{heading}` table must have exactly {len(columns)} cells: {_clip_text(_row_text(cells))}"))
            continue
        rows.append(tuple(cells))
    return rows, problems


def _clip_text(value: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


_ARTIFACT_VERSION = r"[0-9]+(?:\.[0-9]+)*(?:[-+][0-9A-Za-z.-]+)?"
_ARTIFACT_GRAMMARS = {
    "version": re.compile(rf"^version:{_ARTIFACT_VERSION}$"),
    "build": re.compile(r"^build:[a-z0-9][a-z0-9._-]*#[0-9]+$"),
    "image": re.compile(r"^image:[A-Za-z0-9][A-Za-z0-9._/-]*@sha256:[0-9a-f]{64}$"),
    "package": re.compile(rf"^package:@?[A-Za-z0-9][A-Za-z0-9._/-]*@{_ARTIFACT_VERSION}$"),
    "commit": re.compile(r"^commit:[0-9a-fA-F]{7,40}$"),
}
ARTIFACT_KINDS = tuple(_ARTIFACT_GRAMMARS)
_CONTRACT_BINDING = re.compile(r"^(F-\d+)@v([0-9]+):(c1:[0-9a-f]{64})$")
CHECKED_BASES = ("checked", "attested")
QA_METHODS = ("automated", "manual", "exploratory")
QA_RESULTS = ("pass", "fail", "blocked")
RELEASE_OUTCOMES = ("pending", "released", "failed")
_NO_VALUE = {"", "-", "—", "–"}
_APP_ID_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ENVIRONMENT_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def clean_cell(value: str) -> str:
    """A table cell without the backticks that wrap an artifact or identifier."""

    return value.strip().strip("`").strip()


def artifact_reference_problem(value: str) -> str | None:
    """Why `value` is not an artifact reference of CONTRACTS 5.1, or ``None`` when it is one.

    An artifact is `version:`, `build:`, `image:`, `package:` or `commit:` followed by the grammar of its kind. The board
    checks the grammar only, never that the artifact exists.
    """

    text = clean_cell(value)
    kind = text.split(":", 1)[0]
    grammar = _ARTIFACT_GRAMMARS.get(kind)
    if grammar is None:
        return f"must start with one of {', '.join(f'`{item}:`' for item in ARTIFACT_KINDS)}"
    if not grammar.match(text):
        examples = {
            "version": "`version:1.4.0`",
            "build": "`build:catalog-api#412`",
            "image": "`image:registry/app@sha256:<64 hex digits>`",
            "package": "`package:name@1.4.0`",
            "commit": "`commit:<7 to 40 hex digits>`",
        }
        return f"does not match the `{kind}:` form, for example {examples[kind]}"
    return None


@dataclass(frozen=True)
class DeliveryRow:
    """One row of `## Delivery evidence`: the artifact an app delivered, bound to a contract version and its proof."""

    app: str
    artifact: str
    contract: str
    implementation: str
    tests: str
    basis: str
    cells: tuple[str, ...]

    @property
    def text(self) -> str:
        return _row_text(self.cells)

    @property
    def contract_binding(self) -> tuple[str, int, str] | None:
        """(feature ID, version, digest) of the contract cited, or ``None`` for `none`."""

        match = _CONTRACT_BINDING.match(clean_cell(self.contract))
        return (match.group(1), int(match.group(2)), match.group(3)) if match else None


def parse_delivery_rows(body: str) -> tuple[list[DeliveryRow], list[EvidenceProblem]]:
    """The rows of `## Delivery evidence` (CONTRACTS 5.1) and the problems with them."""

    cell_rows, problems = parse_evidence_table(body, "Delivery evidence", DELIVERY_EVIDENCE_COLUMNS, "delivery_evidence_invalid")
    rows: list[DeliveryRow] = []
    for cells in cell_rows:
        app, artifact, contract, implementation, tests, basis = cells
        subject = app.strip() or None
        if not _APP_ID_TOKEN.match(app.strip()):
            problems.append(EvidenceProblem("delivery_evidence_invalid", "Every delivery evidence row must name an app.", subject))
            continue
        row = DeliveryRow(app.strip(), clean_cell(artifact), clean_cell(contract), implementation, tests, clean_cell(basis).lower(), cells)
        rows.append(row)
        reason = artifact_reference_problem(artifact)
        if reason is not None:
            problems.append(EvidenceProblem("artifact_reference_invalid", f"The artifact of `{row.app}` {reason}.", row.app))
        if row.contract.lower() != "none" and row.contract_binding is None:
            problems.append(
                EvidenceProblem(
                    "delivery_evidence_invalid",
                    f"The contract of `{row.app}` must be `none` or `<feature ID>@v<version>:c1:<64 hex digits>`.",
                    row.app,
                )
            )
        for column, value in (("Implementation", implementation), ("Tests", tests)):
            if not _substantive_evidence_cell(value):
                problems.append(EvidenceProblem("delivery_evidence_invalid", f"The {column} cell of `{row.app}` is empty or still a placeholder.", row.app))
        if row.basis not in CHECKED_BASES:
            problems.append(EvidenceProblem("basis_invalid", f"The basis of `{row.app}` must be `checked` or `attested`.", row.app))
    return rows, problems


@dataclass(frozen=True)
class CriterionRef:
    """A criterion cited by a QA row: its number and the revision (`v1:<hex>`) the verification covers."""

    number: int
    revision: str

    @property
    def text(self) -> str:
        return f"AC-{self.number}@{self.revision}"


_CRITERION_REF = re.compile(r"^AC-([0-9]+)@(v1:[0-9a-f]{64})$")


@dataclass(frozen=True)
class QaRow:
    """One row of `## QA verification` (CONTRACTS 5.2): an app row, or an integration row of two or more participants."""

    key: str
    apps: tuple[str, ...]
    integration: bool
    criteria: tuple[CriterionRef, ...]
    method: str
    artifacts: Mapping[str, str]
    environment: str
    attempt: int | None
    result: str
    evidence: str
    basis: str
    cells: tuple[str, ...]

    @property
    def text(self) -> str:
        return _row_text(self.cells)


def parse_qa_rows(body: str) -> tuple[list[QaRow], list[EvidenceProblem]]:
    """The rows of `## QA verification` and the problems with them."""

    cell_rows, problems = parse_evidence_table(body, "QA verification", QA_VERIFICATION_COLUMNS, "qa_row_invalid")
    rows: list[QaRow] = []

    def problem(message: str, subject: str | None) -> None:
        problems.append(EvidenceProblem("qa_row_invalid", message, subject))

    for cells in cell_rows:
        key_cell, criteria_cell, method, artifact_cell, environment, attempt_cell, result, evidence, basis = cells
        key = clean_cell(key_cell)
        integration = key.startswith("integration:")
        if integration:
            apps = tuple(part.strip() for part in key[len("integration:"):].split("+"))
            if len(apps) < 2 or any(not _APP_ID_TOKEN.match(app) for app in apps) or list(apps) != sorted(set(apps)):
                problem(f"The row `{key}` must name two or more participants, sorted and joined by `+`.", key)
                continue
        elif _APP_ID_TOKEN.match(key):
            apps = (key,)
        else:
            problem("Every QA verification row must name an app or `integration:` and its participants.", key or None)
            continue
        refs: list[CriterionRef] = []
        bad_refs = False
        for item in criteria_cell.split(","):
            match = _CRITERION_REF.match(clean_cell(item))
            if match is None:
                bad_refs = True
                break
            refs.append(CriterionRef(int(match.group(1)), match.group(2)))
        if bad_refs or not refs or len({ref.number for ref in refs}) != len(refs):
            problem(f"The criteria of `{key}` must be distinct `AC-<n>@v1:<64 hex digits>` references joined by commas.", key)
            continue
        artifacts: dict[str, str] = {}
        artifact_problem: str | None = None
        if integration:
            for part in artifact_cell.split(";"):
                app, _, artifact = part.partition("=")
                app = app.strip()
                if app in artifacts or app not in apps or artifact_reference_problem(artifact) is not None:
                    artifact_problem = f"The artifacts of `{key}` must be one `app=artifact` entry per participant, joined by `;`."
                    break
                artifacts[app] = clean_cell(artifact)
            if artifact_problem is None and set(artifacts) != set(apps):
                artifact_problem = f"The artifacts of `{key}` must be one `app=artifact` entry per participant, joined by `;`."
        else:
            reason = artifact_reference_problem(artifact_cell)
            if reason is not None:
                artifact_problem = f"The artifact of `{key}` {reason}."
            else:
                artifacts[apps[0]] = clean_cell(artifact_cell)
        if artifact_problem is not None:
            problems.append(EvidenceProblem("artifact_reference_invalid", artifact_problem, key))
            continue
        attempt_match = re.fullmatch(r"qa-([1-9][0-9]*)", clean_cell(attempt_cell))
        row = QaRow(
            key,
            apps,
            integration,
            tuple(refs),
            clean_cell(method).lower(),
            artifacts,
            clean_cell(environment),
            int(attempt_match.group(1)) if attempt_match else None,
            clean_cell(result).lower(),
            evidence,
            clean_cell(basis).lower(),
            cells,
        )
        rows.append(row)
        if row.method not in QA_METHODS:
            problem(f"The method of `{key}` must be one of {', '.join(QA_METHODS)}.", key)
        if not _ENVIRONMENT_TOKEN.match(row.environment):
            problem(f"The environment of `{key}` must be a short name such as `staging`.", key)
        if row.attempt is None:
            problem(f"The attempt of `{key}` must be `qa-<n>`.", key)
        if row.result not in QA_RESULTS:
            problem(f"The result of `{key}` must be one of {', '.join(QA_RESULTS)}.", key)
        if not _substantive_evidence_cell(evidence):
            problem(f"The evidence of `{key}` is empty or still a placeholder.", key)
        if row.basis not in CHECKED_BASES:
            problems.append(EvidenceProblem("basis_invalid", f"The basis of `{key}` must be `checked` or `attested`.", key))
    return rows, problems


@dataclass(frozen=True)
class ReleaseRow:
    """One row of `## Release` (CONTRACTS 5.3). A row with an attempt `release-<n>` is the authoritative row of its app."""

    app: str
    target: str
    version: str
    attempt: int | None
    outcome: str
    record: str
    basis: str
    cells: tuple[str, ...]

    @property
    def authoritative(self) -> bool:
        return self.attempt is not None

    @property
    def text(self) -> str:
        return _row_text(self.cells)


def parse_release_rows(body: str) -> tuple[list[ReleaseRow], list[EvidenceProblem]]:
    """The rows of `## Release` and the problems with them."""

    cell_rows, problems = parse_evidence_table(body, "Release", RELEASE_COLUMNS, "release_row_invalid")
    rows: list[ReleaseRow] = []
    for cells in cell_rows:
        app, target, version, attempt_cell, outcome, record, basis = cells
        app = app.strip()
        if not _APP_ID_TOKEN.match(app):
            problems.append(EvidenceProblem("release_row_invalid", "Every Release row must name an app.", app or None))
            continue
        attempt_text = clean_cell(attempt_cell)
        attempt_match = re.fullmatch(r"release-([1-9][0-9]*)", attempt_text)
        row = ReleaseRow(
            app,
            clean_cell(target),
            clean_cell(version),
            int(attempt_match.group(1)) if attempt_match else None,
            clean_cell(outcome).lower(),
            record.strip(),
            clean_cell(basis).lower(),
            cells,
        )
        rows.append(row)

        def bad(message: str) -> None:
            problems.append(EvidenceProblem("release_row_invalid", message, app))

        if attempt_match is None and attempt_text not in _NO_VALUE:
            bad(f"The attempt of `{app}` must be `release-<n>`, or `—` for a staging row.")
        if row.outcome not in RELEASE_OUTCOMES:
            bad(f"The outcome of `{app}` must be one of {', '.join(RELEASE_OUTCOMES)}.")
        reason = artifact_reference_problem(version)
        if reason is not None:
            problems.append(EvidenceProblem("artifact_reference_invalid", f"The version of `{app}` {reason}.", app))
        if row.authoritative and row.outcome in {"released", "failed"}:
            if row.target in _NO_VALUE or record.strip() in _NO_VALUE or row.basis not in CHECKED_BASES:
                bad(f"A `{row.outcome}` Release row of `{app}` needs a target, a record and a `checked` or `attested` basis.")
        elif row.authoritative and row.outcome == "pending" and (row.target not in _NO_VALUE or record.strip() not in _NO_VALUE or row.basis not in _NO_VALUE):
            bad(f"A `pending` Release row of `{app}` has target `—`, record `—` and basis `—`.")
        elif not row.authoritative and row.target in _NO_VALUE:
            bad(f"A staging Release row of `{app}` names its environment as the target.")
    return rows, problems


@dataclass(frozen=True)
class FeatureEvidence:
    """The three evidence tables of a feature page and the problems found while reading them."""

    delivery: tuple[DeliveryRow, ...] = ()
    qa: tuple[QaRow, ...] = ()
    release: tuple[ReleaseRow, ...] = ()
    problems: tuple[EvidenceProblem, ...] = ()

    @property
    def has_rows(self) -> bool:
        return bool(self.delivery or self.qa or self.release)

    def delivery_row(self, app: str) -> DeliveryRow | None:
        return next((row for row in self.delivery if row.app == app), None)

    def authoritative_release(self, app: str) -> ReleaseRow | None:
        return next((row for row in self.release if row.app == app and row.authoritative), None)

    def qa_rows_naming(self, app: str) -> list[QaRow]:
        return [row for row in self.qa if app in row.apps]


def read_feature_evidence(body: str) -> FeatureEvidence:
    """Parse `## Delivery evidence`, `## QA verification` and `## Release` of a feature page body."""

    delivery, delivery_problems = parse_delivery_rows(body)
    qa, qa_problems = parse_qa_rows(body)
    release, release_problems = parse_release_rows(body)
    return FeatureEvidence(tuple(delivery), tuple(qa), tuple(release), tuple([*delivery_problems, *qa_problems, *release_problems]))


# --- Evidence history ----------------------------------------------------------------------------------------------

HISTORY_HEADING = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s+-\s+([a-z][a-z0-9-]*)\s*$")
HISTORY_LABELS = (
    "Reason",
    "Affected apps",
    "Participants",
    "Affected tracks",
    "Archived evidence",
    "Reaffirmed evidence",
    "Requirement/API invalidations",
    "Linked bugs",
)
ARCHIVED_SECTIONS = ("Delivery evidence", "QA verification", "Release", "Fix", "Verification")
_HEADING_ANY = re.compile(r"^\s{0,3}#{1,6}\s")


@dataclass(frozen=True)
class HistoryEntry:
    """One entry of `## Evidence history` (CONTRACTS 2.7)."""

    date: str
    action: str
    heading: str
    text: str
    fields: Mapping[str, str]

    def names(self, label: str) -> list[str]:
        """The identifiers a labelled field lists (`none` and brackets are ignored)."""

        value = self.fields.get(label, "").splitlines()[0] if self.fields.get(label) else ""
        items = [part.strip().strip("`[]").strip() for part in re.split(r"[,;]", value)]
        return [item for item in items if item and item.lower() != "none"]

    @property
    def affected_apps(self) -> list[str]:
        return self.names("Affected apps")

    @property
    def participants(self) -> list[str]:
        return self.names("Participants")

    def rows(self, label: str) -> list[tuple[str, tuple[str, ...]]]:
        """The table rows of a block field as (section name, the row's own cells)."""

        found: list[tuple[str, tuple[str, ...]]] = []
        for line in self.fields.get(label, "").splitlines():
            stripped = re.sub(r"^[-*+]\s+", "", line.strip())
            if not stripped.startswith("|"):
                continue
            cells = _split_table_row(stripped)
            if _is_separator_row(cells) or not cells or cells[0] not in ARCHIVED_SECTIONS:
                continue
            found.append((cells[0], tuple(cells[1:])))
        return found

    @property
    def archived_rows(self) -> list[tuple[str, tuple[str, ...]]]:
        return self.rows("Archived evidence")

    @property
    def reaffirmed_rows(self) -> list[tuple[str, tuple[str, ...]]]:
        return self.rows("Reaffirmed evidence")


def _label_blocks(text: str) -> dict[str, str]:
    """The labelled bullets (`- Label: text`) of an entry, each with the lines below it up to the next label or heading."""

    labels = "|".join(re.escape(item) for item in HISTORY_LABELS)
    head = re.compile(rf"^\s*-\s*({labels}):[ \t]*(.*)$")
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = head.match(line)
        if match:
            current = match.group(1)
            fields[current] = [match.group(2).strip()]
        elif _HEADING_ANY.match(line):
            current = None
        elif current is not None:
            fields[current].append(line)
    return {label: "\n".join(lines).strip() for label, lines in fields.items()}


def parse_evidence_history(body: str) -> list[HistoryEntry]:
    """The entries of `## Evidence history` in the order written."""

    section = section_text(body, "Evidence history")
    entries: list[HistoryEntry] = []
    block: list[str] = []
    heading: tuple[str, str, str] | None = None

    def close() -> None:
        if heading is not None:
            text = "\n".join(block)
            entries.append(HistoryEntry(heading[0], heading[1], heading[2], text, _label_blocks(text)))

    for line in section.splitlines():
        match = HISTORY_HEADING.match(line.strip())
        if match:
            close()
            heading = (match.group(1), match.group(2), line.strip())
            block = []
        elif heading is not None:
            block.append(line)
    close()
    return entries


# --- Design tracks -------------------------------------------------------------------------------------------------

DESIGN_TRACKS = ("ui", "technical")
TRACK_STATES = ("pending", "done", "not-applicable")
NO_UI_TRACK_REASON = "No app in scope has a UI."
_TRACK_KEYS = ("ui", "technical", "ui-reason", "technical-reason")


@dataclass(frozen=True)
class DesignTracks:
    """The `design-tracks` and `design-reaffirm` front matter of a feature in design or later (CONTRACTS 3.1)."""

    ui: str
    technical: str
    ui_reason: str | None = None
    technical_reason: str | None = None
    reaffirm: tuple[str, ...] = ()

    def state(self, track: str) -> str:
        return self.ui if track == "ui" else self.technical

    def reason(self, track: str) -> str | None:
        return self.ui_reason if track == "ui" else self.technical_reason

    def resolved(self, track: str) -> bool:
        return self.state(track) in {"done", "not-applicable"}

    @property
    def unresolved(self) -> list[str]:
        return [track for track in DESIGN_TRACKS if not self.resolved(track)]

    def tracks_value(self) -> dict[str, str]:
        """The `design-tracks` mapping in the order of the contract: both states, then the reasons that exist."""

        value = {"ui": self.ui, "technical": self.technical}
        if self.ui_reason is not None:
            value["ui-reason"] = self.ui_reason
        if self.technical_reason is not None:
            value["technical-reason"] = self.technical_reason
        return value

    def reaffirm_value(self) -> list[str]:
        return [track for track in DESIGN_TRACKS if track in self.reaffirm]

    def frontmatter(self) -> dict[str, Any]:
        """Both front matter keys, which are written together."""

        return {"design-tracks": self.tracks_value(), "design-reaffirm": self.reaffirm_value()}

    def with_track(self, track: str, state: str, reason: str | None = None) -> "DesignTracks":
        """A copy with one track set to `state`; a reason is kept only for `not-applicable`."""

        reason = reason if state == "not-applicable" else None
        if track == "ui":
            return _replace_tracks(self, ui=state, ui_reason=reason)
        return _replace_tracks(self, technical=state, technical_reason=reason)

    def with_reaffirm(self, tracks: Iterable[str]) -> "DesignTracks":
        wanted = set(tracks)
        return _replace_tracks(self, reaffirm=tuple(track for track in DESIGN_TRACKS if track in wanted))


def _replace_tracks(tracks: DesignTracks, **changes: Any) -> DesignTracks:
    values: dict[str, Any] = {
        "ui": tracks.ui,
        "technical": tracks.technical,
        "ui_reason": tracks.ui_reason,
        "technical_reason": tracks.technical_reason,
        "reaffirm": tracks.reaffirm,
    }
    values.update(changes)
    return DesignTracks(**values)


def parse_design_tracks(frontmatter: Mapping[str, Any]) -> tuple[DesignTracks | None, list[str]]:
    """The design tracks of a feature page and the problems with their shape (`design-tracks-invalid`).

    ``(None, [])`` is a page that has neither key. A reason belongs only to a `not-applicable` track and is a string; whether a
    reason is blank is a prerequisite of the action that sets the track, not part of the shape.
    """

    has_tracks = "design-tracks" in frontmatter
    has_reaffirm = "design-reaffirm" in frontmatter
    if not has_tracks and not has_reaffirm:
        return None, []
    if not has_tracks:
        return None, ["`design-reaffirm` exists without `design-tracks`; the two keys are written together."]
    value = frontmatter["design-tracks"]
    problems: list[str] = []
    if not isinstance(value, Mapping):
        return None, ["`design-tracks` must be a mapping with the keys `ui` and `technical`."]
    unknown = sorted(str(key) for key in value if key not in _TRACK_KEYS)
    if unknown:
        problems.append(
            f"`design-tracks` has unsupported key(s) {', '.join(f'`{key}`' for key in unknown)}; the keys are {', '.join(f'`{key}`' for key in _TRACK_KEYS)}."
        )
    states: dict[str, str] = {}
    for track in DESIGN_TRACKS:
        state = value.get(track)
        if not isinstance(state, str) or state not in TRACK_STATES:
            problems.append(f"`design-tracks.{track}` must be one of {', '.join(f'`{item}`' for item in TRACK_STATES)}.")
            continue
        states[track] = state
    reasons: dict[str, str | None] = {}
    for track in DESIGN_TRACKS:
        key = f"{track}-reason"
        if key not in value:
            reasons[track] = None
            continue
        reason = value[key]
        if not isinstance(reason, str):
            problems.append(f"`design-tracks.{key}` must be a string.")
            reasons[track] = None
        elif states.get(track) != "not-applicable":
            problems.append(f"`design-tracks.{key}` exists only while `{track}` is `not-applicable`.")
            reasons[track] = None
        else:
            reasons[track] = reason
    reaffirm: list[str] = []
    if has_reaffirm:
        listed = frontmatter["design-reaffirm"]
        if not isinstance(listed, list):
            problems.append("`design-reaffirm` must be a list of tracks (`ui`, `technical`).")
        else:
            for item in listed:
                if not isinstance(item, str) or item not in DESIGN_TRACKS:
                    problems.append("`design-reaffirm` lists only the tracks `ui` and `technical`.")
                elif item in reaffirm:
                    problems.append(f"`design-reaffirm` lists `{item}` twice.")
                else:
                    reaffirm.append(item)
    if problems or len(states) != 2:
        return None, problems
    for track in reaffirm:
        if states[track] != "done":
            problems.append(f"`design-reaffirm` lists `{track}`, which is `{states[track]}`; only a `done` track is reaffirmed.")
    if problems:
        return None, problems
    ordered = tuple(item for item in DESIGN_TRACKS if item in reaffirm)
    return DesignTracks(states["ui"], states["technical"], reasons["ui"], reasons["technical"], ordered), []


def scope_has_ui(apps: Iterable[str], model: WorkspaceModel | None) -> bool:
    """Whether an active app of the scope has a UI (`has-ui` true or unknown), which makes the design owner the designer."""

    return design_owner(list(apps), model) == "designer"


def ui_apps(apps: Iterable[str], model: WorkspaceModel | None) -> list[str]:
    """The active apps of a scope whose `has-ui` is true or unknown, in the order of the scope."""

    if model is None:
        return list(apps)
    return [app_id for app_id in apps if (app := model.app(app_id)) is not None and app.active and app.gate_capability(CAPABILITY_HAS_UI)]


def initial_design_tracks(apps: Iterable[str], model: WorkspaceModel | None) -> DesignTracks:
    """The tracks of a feature that starts design or whose scope changed (CONTRACTS 3.1, 2.9): `technical: pending`, and the UI
    track `pending` or, when every active scoped app has `has-ui: false`, `not-applicable` with the standard reason."""

    if scope_has_ui(apps, model):
        return DesignTracks("pending", "pending")
    return DesignTracks("not-applicable", "pending", NO_UI_TRACK_REASON, None)


def normalize_ui_track(tracks: DesignTracks, apps: Iterable[str], model: WorkspaceModel | None) -> DesignTracks:
    """The no-UI initialization applied to existing tracks: a pending UI track of a scope with no UI becomes `not-applicable`."""

    if tracks.ui == "pending" and not scope_has_ui(apps, model):
        return tracks.with_track("ui", "not-applicable", NO_UI_TRACK_REASON)
    return tracks


def track_of_page(relative: str) -> str | None:
    """The track a workspace path belongs to: `ui` for a design page, `technical` for a technical design page or an API contract."""

    parts = PurePosixPath(relative).parts
    if len(parts) >= 4 and parts[:2] == ("knowledge", "wiki"):
        if parts[2] == "design":
            return "ui"
        if parts[2] in {"technical-design", "api-contracts"}:
            return "technical"
    return None


# --- Technical design and the API contract -------------------------------------------------------------------------

TECHNICAL_DESIGN_SECTIONS = (
    "Summary",
    "Architecture impact",
    "Data model and migrations",
    "Security and privacy",
    "Non-functional requirements",
    "Risks",
    "Decisions",
    "API contract",
    "Test strategy",
)
TECHNICAL_DESIGN_FIELDS = ("feature-id", "title", "apps", "decisions")
ARCHITECTURE_IMPACT_COLUMNS = ("app", "modules", "change")
TEST_STRATEGY_COLUMNS = ("criterion", "applies to", "method", "level", "notes")
_TEST_STRATEGY_CRITERION = re.compile(r"^AC-([0-9]+)$")
_PLACEHOLDER_TEXT = re.compile(r"\b(?:TODO|TBD|FIXME|placeholder)\b|^\[[^\]]*\]$", re.IGNORECASE)


@dataclass(frozen=True)
class StrategyRow:
    """One row of the Test strategy table: a criterion and how QA verifies it."""

    criterion: str
    applies_to: tuple[str, ...]
    method: str
    level: str
    notes: str


def _has_content(text: str) -> bool:
    """Whether a section holds text of its own: some visible line that is not a bare template placeholder."""

    lines = [
        line
        for line in _visible_markdown_lines(text)
        if not _is_separator_row(_split_table_row(line)) and not re.fullmatch(r"[#>*\-\s]*", line)
    ]
    if not lines:
        return False
    joined = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return bool(re.search(r"\w", joined)) and not _PLACEHOLDER_TEXT.search(joined)


def parse_test_strategy(body: str) -> tuple[list[StrategyRow], list[str]]:
    """The rows of the `## Test strategy` table and the problems with them (messages)."""

    cell_rows, table_problems = parse_evidence_table(body, "Test strategy", TEST_STRATEGY_COLUMNS, "test-strategy-incomplete")
    problems = [item.message for item in table_problems]
    rows: list[StrategyRow] = []
    for criterion, applies, method, level, notes in cell_rows:
        criterion = clean_cell(criterion)
        if not _TEST_STRATEGY_CRITERION.match(criterion):
            problems.append(f"The criterion cell `{_clip_text(criterion, 40)}` of the Test strategy is not a criterion ID such as `AC-1`.")
            continue
        listed = re.sub(r"(?i)^\s*\[?\s*integration\s*:", "", applies)
        targets = tuple(item for item in (part.strip().strip("`[]").strip() for part in re.split(r"[,;]", listed)) if item)
        if not targets:
            problems.append(f"The Test strategy row of `{criterion}` names no app under Applies to.")
        method = clean_cell(method).lower()
        if method not in QA_METHODS:
            problems.append(f"The method of `{criterion}` in the Test strategy must be one of {', '.join(f'`{item}`' for item in QA_METHODS)}.")
        if not clean_cell(level):
            problems.append(f"The Test strategy row of `{criterion}` has no level (unit, integration, end-to-end or another).")
        rows.append(StrategyRow(criterion, targets, method, clean_cell(level), notes.strip()))
    return rows, problems


def technical_design_problems(
    frontmatter: Mapping[str, Any],
    body: str,
    *,
    feature_id: str,
    scope: Iterable[str],
    criteria_ids: Iterable[str],
    check_strategy: bool = True,
) -> list[tuple[str, str]]:
    """Why a technical design page is not complete, as (code, message) pairs; empty when it is (CONTRACTS 6.2).

    `scope` are the active apps of the feature: each one is named in `apps` and in the Architecture impact table.
    `criteria_ids` are the feature's criterion IDs (`AC-1`): each one is named in the Test strategy.
    """

    problems: list[tuple[str, str]] = []
    incomplete = "technical-design-incomplete"
    scope_apps = list(scope)
    unknown = sorted(str(key) for key in frontmatter if key not in TECHNICAL_DESIGN_FIELDS)
    if unknown:
        problems.append(
            (
                incomplete,
                f"The technical design page has unsupported front matter field(s) {', '.join(f'`{key}`' for key in unknown)}; its fields are {', '.join(f'`{key}`' for key in TECHNICAL_DESIGN_FIELDS)}.",
            )
        )
    page_feature = frontmatter.get("feature-id")
    if not isinstance(page_feature, str) or page_feature.strip().lower() != feature_id.strip().lower():
        problems.append((incomplete, f"`feature-id` of the technical design page must be `{feature_id}`."))
    if not isinstance(frontmatter.get("title"), str) or not frontmatter["title"].strip():
        problems.append((incomplete, "The technical design page needs a non-empty `title`."))
    apps = frontmatter.get("apps")
    if not isinstance(apps, list) or not apps or any(not isinstance(item, str) or not item.strip() for item in apps):
        problems.append((incomplete, "`apps` of the technical design page must list the apps it covers."))
        apps = []
    missing_apps = [app for app in scope_apps if app not in apps]
    if missing_apps:
        problems.append((incomplete, f"`apps` of the technical design page must name every app of the scope; missing {', '.join(f'`{app}`' for app in missing_apps)}."))
    decisions = frontmatter.get("decisions")
    if not isinstance(decisions, list) or any(not isinstance(item, str) for item in decisions):
        problems.append((incomplete, "`decisions` of the technical design page must be a list of ADR IDs (an empty list when there are none)."))
    for heading in TECHNICAL_DESIGN_SECTIONS:
        if not _has_content(section_text(body, heading)):
            problems.append((incomplete, f"The technical design page needs content under `## {heading}`."))
    impact_rows, impact_problems = parse_evidence_table(body, "Architecture impact", ARCHITECTURE_IMPACT_COLUMNS, incomplete)
    problems.extend((incomplete, item.message) for item in impact_problems)
    if section_text(body, "Architecture impact").strip() and not impact_rows and not impact_problems:
        problems.append((incomplete, "The Architecture impact table has no row; list the app, its modules and the change."))
    for row in impact_rows:
        if any(not cell.strip() for cell in row):
            problems.append((incomplete, f"An Architecture impact row of `{clean_cell(row[0]) or '?'}` has an empty cell."))
    impact_apps = {clean_cell(row[0]) for row in impact_rows}
    uncovered = [app for app in scope_apps if app not in impact_apps]
    if uncovered and impact_rows:
        problems.append((incomplete, f"The Architecture impact table must name every app of the scope; missing {', '.join(f'`{app}`' for app in uncovered)}."))
    if check_strategy:
        strategy, strategy_problems = parse_test_strategy(body)
        problems.extend(("test-strategy-incomplete", message) for message in strategy_problems)
        named = {row.criterion for row in strategy}
        wanted = list(criteria_ids)
        absent = [item for item in wanted if item not in named]
        if absent:
            problems.append(("test-strategy-incomplete", f"The Test strategy must name every acceptance criterion; missing {', '.join(f'`{item}`' for item in absent)}."))
        stray = sorted(named - set(wanted), key=lambda item: int(item.split("-")[1]))
        if stray:
            problems.append(("test-strategy-incomplete", f"The Test strategy names {', '.join(f'`{item}`' for item in stray)}, which the feature does not have."))
        outside = sorted({app for row in strategy for app in row.applies_to if scope_apps and app not in scope_apps})
        if outside:
            problems.append(("test-strategy-incomplete", f"The Test strategy names app(s) {', '.join(f'`{app}`' for app in outside)} outside the feature's scope."))
    return problems


def contract_sections(body: str) -> list[list[str]]:
    """The ordered sections of an API contract body as [heading, text] pairs, NFC with whitespace collapsed (CONTRACTS 3.4).

    Text before the first `##` heading is a section with the empty heading, so a change there changes the digest too.
    """

    def clean(value: str) -> str:
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()

    sections: list[list[str]] = []
    heading = ""
    lines: list[str] = []
    started = False
    for line in body.splitlines():
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line.strip())
        if match:
            if started or clean("\n".join(lines)):
                sections.append([clean(heading), clean("\n".join(lines))])
            heading, lines, started = match.group(1), [], True
        else:
            lines.append(line)
    if started or clean("\n".join(lines)):
        sections.append([clean(heading), clean("\n".join(lines))])
    return sections


def contract_digest(feature_id: str, version: int, body: str) -> str:
    """`c1:` followed by the SHA-256 of the canonical JSON `[1, feature_id, version, sections]`.

    Front matter other than `version` is not part of it, so a contract that becomes `implemented` keeps its digest.
    """

    payload = canonical_json([1, feature_id.strip().upper(), version, contract_sections(body)])
    return "c1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def contract_citation(feature_id: str, version: int, body: str) -> str:
    """The Contract cell a delivery row cites: `<feature ID>@v<version>:<digest>`."""

    return f"{feature_id.strip().upper()}@v{version}:{contract_digest(feature_id, version, body)}"


def contract_page_citation(frontmatter: Mapping[str, Any], body: str) -> str | None:
    """The citation of an API contract page, or ``None`` when its `feature-id` or `version` is not usable."""

    feature = frontmatter.get("feature-id")
    version = frontmatter.get("version")
    if not isinstance(feature, str) or not re.fullmatch(r"F-\d+", feature.strip(), re.IGNORECASE):
        return None
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        return None
    return contract_citation(feature, version, body)


# --- Acceptance criteria -------------------------------------------------------------------------------------------

_CRITERION_ITEM = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]|\d+[.)])[ \t]+(?:\[(?P<check>[ xX])\][ \t]+)?(?P<rest>.*)$")
_CRITERION_LABEL = re.compile(r"^\*\*(?P<label>Decided|Observed|Proposed|Assumed|Unknown):\*\*[ \t]*(?P<rest>.*)$")
_CRITERION_ID = re.compile(r"^AC-(?P<number>[0-9]+)(?:[ \t]+(?P<rest>.*))?$")
_CRITERION_SCOPE = re.compile(r"^\[(?P<scope>[^\]]*)\][ \t]*(?P<text>.*)$")
_LINK_IN_TEXT = re.compile(r"(?<!!)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?[^)]*\)")


@dataclass(frozen=True)
class Criterion:
    """One acceptance criterion of a feature page (CONTRACTS 4.1).

    `number` and `applies_to` are ``None``/empty when the entry has no valid ID or no valid `applies-to`; `problems` lists
    why. `revision` is `v1:<64 hex>` once the entry is complete.
    """

    line: int
    raw: str
    checked: bool
    label: str
    number: int | None
    applies_to: tuple[str, ...]
    integration: bool
    text: str
    revision: str | None
    problems: tuple[tuple[str, str], ...] = ()

    @property
    def id(self) -> str | None:
        return f"AC-{self.number}" if self.number is not None else None

    @property
    def ref(self) -> str | None:
        return f"AC-{self.number}@{self.revision}" if self.number is not None and self.revision else None

    @property
    def participants(self) -> tuple[str, ...]:
        return self.applies_to

    def names(self, app: str) -> bool:
        return app in self.applies_to


def criterion_text(value: str) -> str:
    """The text of a criterion as its revision reads it: NFC, links as `text <destination>`, whitespace collapsed."""

    rendered = _LINK_IN_TEXT.sub(lambda match: f"{match.group(1)} <{match.group(2)}>", value)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", rendered)).strip()


def criterion_revision(feature_id: str, number: int, applies_to: Iterable[str], integration: bool, label: str, text: str) -> str:
    """`v1:` and the SHA-256 of the canonical JSON `[1, feature_id, criterion_id, applies_to, label, text]` (CONTRACTS 4.1)."""

    apps = sorted(set(applies_to))
    payload = [1, feature_id, f"AC-{number}", {"integration": apps} if integration else apps, label, text]
    return "v1:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _raw_visible_lines(text: str) -> list[tuple[int, str]]:
    """The lines of `text` outside code fences and HTML comments as (index, raw line), indentation kept."""

    visible: list[tuple[int, str]] = []
    fenced = False
    in_comment = False
    for index, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if line.startswith("```") or line.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            continue
        visible.append((index, raw))
    return visible


def parse_criteria(body: str, feature_id: str) -> list[Criterion]:
    """The acceptance criteria of a feature page body, with their IDs, `applies-to`, text and revisions.

    Every list item of `## Acceptance criteria` is one criterion; an indented line below it continues it.
    """

    section = section_text(body, "Acceptance criteria")
    items: list[tuple[int, str, bool, str]] = []  # (line, raw first line, checked, text so far)
    for index, raw in _raw_visible_lines(section):
        match = _CRITERION_ITEM.match(raw)
        if match:
            items.append((index, raw.strip(), (match.group("check") or " ").lower() == "x", match.group("rest").strip()))
        elif items and raw.strip() and raw[:1] in {" ", "\t"}:
            line, first, checked, text = items[-1]
            items[-1] = (line, first, checked, f"{text} {raw.strip()}".strip())
    criteria: list[Criterion] = []
    for line, first, checked, rest in items:
        label = ""
        label_match = _CRITERION_LABEL.match(rest)
        if label_match:
            label = label_match.group("label")
            rest = label_match.group("rest").strip()
        problems: list[tuple[str, str]] = []
        number: int | None = None
        applies: tuple[str, ...] = ()
        integration = False
        text = ""
        id_match = _CRITERION_ID.match(rest)
        if id_match is None:
            problems.append(("criterion-id-required", "A criterion starts with its ID, such as `AC-1 [app] text`."))
        else:
            number = int(id_match.group("number"))
            scope_match = _CRITERION_SCOPE.match((id_match.group("rest") or "").strip())
            if scope_match is None:
                problems.append(("invalid-applies-to", f"`AC-{number}` needs an `applies-to` after its ID: `[app, ...]` or `[integration: app, app, ...]`."))
            else:
                scope = scope_match.group("scope").strip()
                text = scope_match.group("text").strip()
                if scope.lower().startswith("integration:"):
                    integration = True
                    scope = scope[len("integration:"):]
                names = [part.strip() for part in scope.split(",")]
                valid = bool(names) and all(_APP_ID_TOKEN.match(name) for name in names) and len(set(names)) == len(names)
                if integration and len(names) < 2:
                    valid = False
                if not valid:
                    problems.append(
                        (
                            "invalid-applies-to",
                            f"`AC-{number}` has an invalid `applies-to`: use `[app, ...]` for per-app criteria or `[integration: app, app, ...]` with two or more distinct apps.",
                        )
                    )
                    integration = False
                else:
                    applies = tuple(sorted(names))
        normalized = criterion_text(text)
        revision = (
            criterion_revision(feature_id, number, applies, integration, label, normalized)
            if number is not None and applies and not problems
            else None
        )
        criteria.append(Criterion(line, first, checked, label, number, applies, integration, normalized, revision, tuple(problems)))
    return criteria


def criteria_high_water(frontmatter: Mapping[str, Any]) -> tuple[int | None, str | None]:
    """The `criteria-high-water` mark of a feature (``None`` when absent) and the problem with it, if any."""

    if "criteria-high-water" not in frontmatter:
        return None, None
    value = frontmatter["criteria-high-water"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, "`criteria-high-water` must be a non-negative integer, the highest criterion number ever assigned."
    return value, None


# --- Attempts ------------------------------------------------------------------------------------------------------


def qa_attempt(app: str, history: Iterable[HistoryEntry]) -> int:
    """The current QA attempt of an app (CONTRACTS 5.4): 1 plus the entries that list it under Affected apps and archived
    a QA row naming it. An entry that lists the app only as a participant does not count."""

    count = 0
    for entry in history:
        if app not in entry.affected_apps:
            continue
        if any(section == "QA verification" and _qa_row_names(cells, app) for section, cells in entry.archived_rows):
            count += 1
    return 1 + count


def _qa_row_names(cells: tuple[str, ...], app: str) -> bool:
    key = clean_cell(cells[0]) if cells else ""
    if key.startswith("integration:"):
        return app in [part.strip() for part in key[len("integration:"):].split("+")]
    return key == app


def evidence_generation(history: Iterable[HistoryEntry], section: str, app: str) -> int:
    """The generation of an app's active Delivery evidence (or Fix) row (CONTRACTS 1.6): 1 plus the Evidence history entries that archived that app's row of `section`."""

    return 1 + sum(
        1
        for entry in history
        if any(name == section and cells and cells[0].strip() == app for name, cells in entry.archived_rows)
    )


def row_digest(cells: Iterable[str]) -> str:
    """The row digest of an evidence row: `sha256` of its cells, trimmed and joined with `|`."""

    return hashlib.sha256("|".join(cell.strip() for cell in cells).encode("utf-8")).hexdigest()


def bug_qa_attempt(history: Iterable[HistoryEntry]) -> int:
    """The current verification attempt of a bug: 1 plus the entries that archived a Verification row."""

    return 1 + sum(1 for entry in history if any(section == "Verification" for section, _cells in entry.archived_rows))


def release_attempt(records: Iterable[Mapping[str, Any]], item: str, app: str) -> int:
    """The next release attempt of an (item, app): 1 plus the records with a delivery row for it, rollback and redeploy records excluded.

    A record is a mapping with `kind` (`release`, `rollback` or `redeploy`) and `delivery`, the (item, app) pairs it delivers.
    """

    return 1 + sum(
        1
        for record in records
        if record.get("kind", "release") == "release" and (item, app) in {tuple(pair) for pair in record.get("delivery", ())}
    )


# --- App stages and QA coverage ------------------------------------------------------------------------------------


def app_stage(app: str, evidence: FeatureEvidence) -> str:
    """The stage of an active app in a feature at `in-dev` or later (CONTRACTS 4.2): the first rule that matches."""

    release = evidence.authoritative_release(app)
    if release is not None and release.outcome == "released":
        return "released"
    if evidence.delivery_row(app) is None:
        return "in-dev"
    if not evidence.qa_rows_naming(app):
        return "ready-for-qa"
    if release is None:
        return "in-qa"
    if release.outcome in {"pending", "failed"}:
        return "ready-for-release"
    return "in-qa"


def app_stages(apps: Iterable[str], evidence: FeatureEvidence) -> dict[str, str]:
    """The stage of each of `apps`, in the order given."""

    return {app: app_stage(app, evidence) for app in apps}


def minimum_stage(stages: Iterable[str]) -> str | None:
    """The lowest of `stages` in `APP_STAGE_ORDER`, or ``None`` when there are none."""

    ranks = [APP_STAGE_ORDER.index(stage) for stage in stages]
    return APP_STAGE_ORDER[min(ranks)] if ranks else None


def app_stages_text(status: str | None, apps: Iterable[str], body: str, model: WorkspaceModel | None) -> str:
    """The `App stages` cell of the status board (CONTRACTS 8.2): `app: stage; ...` for the active apps, or `—` before `in-dev`."""

    if status_rank(status) < status_rank("in-dev"):
        return "—"
    # A released feature keeps its whole scope as history, so a later retirement does not change its cell.
    scoped = list(apps) if status == "released" else active_scope(apps, model)
    stages = app_stages(scoped, read_feature_evidence(body))
    return "; ".join(f"{app}: {stage}" for app, stage in stages.items()) or "—"


def active_scope(apps: Iterable[str], model: WorkspaceModel | None) -> list[str]:
    """The apps of a scope that are active: a retired app is excluded from stages until it leaves the scope."""

    if model is None:
        return list(apps)
    return [app for app in apps if (item := model.app(app)) is not None and item.active]


@dataclass(frozen=True)
class CoverageGap:
    """One way an app's QA evidence falls short of CONTRACTS 4.4."""

    code: str
    message: str
    criterion: str | None = None


def qa_coverage(
    app: str,
    criteria: Iterable[Criterion],
    evidence: FeatureEvidence,
    history: Iterable[HistoryEntry],
) -> list[CoverageGap]:
    """The gaps in the QA coverage of `app` (CONTRACTS 4.4); an empty list means it is covered.

    1. every criterion listing the app has a passing app row of the app at its current revision, on the app's current
       artifact, in the app's current attempt;
    2. every integration criterion naming the app has a passing integration row of exactly its participants, with every
       participant's artifact current, in the highest attempt of its participants;
    3. no row of the app's current attempt is `fail` or `blocked`.
    """

    entries = list(history)
    gaps: list[CoverageGap] = []
    artifacts = {row.app: clean_cell(row.artifact) for row in evidence.delivery}
    attempt = qa_attempt(app, entries)
    for criterion in criteria:
        if criterion.revision is None or not criterion.names(app) or criterion.id is None:
            continue
        ref = CriterionRef(criterion.number or 0, criterion.revision)
        if criterion.integration:
            expected_attempt = max(qa_attempt(participant, entries) for participant in criterion.applies_to)
            covered = any(
                row.integration
                and set(row.apps) == set(criterion.applies_to)
                and ref in row.criteria
                and row.result == "pass"
                and row.attempt == expected_attempt
                and all(row.artifacts.get(participant) == artifacts.get(participant) for participant in row.apps)
                for row in evidence.qa
            )
            if not covered:
                gaps.append(
                    CoverageGap(
                        "integration_not_covered",
                        f"Integration criterion `{criterion.id}` has no passing row of {', '.join(f'`{item}`' for item in criterion.applies_to)} "
                        "at its current revision on every participant's current artifact.",
                        criterion.id,
                    )
                )
        else:
            covered = any(
                not row.integration
                and row.apps == (app,)
                and ref in row.criteria
                and row.result == "pass"
                and row.attempt == attempt
                and row.artifacts.get(app) == artifacts.get(app)
                for row in evidence.qa
            )
            if not covered:
                gaps.append(
                    CoverageGap(
                        "criterion_not_covered",
                        f"Criterion `{criterion.id}` has no passing row of `{app}` at its current revision on its current artifact in attempt qa-{attempt}.",
                        criterion.id,
                    )
                )
    failing = [row for row in evidence.qa_rows_naming(app) if row.attempt == (max(qa_attempt(item, entries) for item in row.apps) if row.integration else attempt) and row.result in {"fail", "blocked"}]
    if failing:
        gaps.append(CoverageGap("qa_result_failed", f"`{app}` has a `{failing[0].result}` result in its current attempt (row `{failing[0].key}`)."))
    return gaps


def stale_qa_rows(
    criteria: Iterable[Criterion],
    evidence: FeatureEvidence,
    history: Iterable[HistoryEntry],
    *,
    skip_apps: Iterable[str] = (),
) -> list[tuple[QaRow, str]]:
    """The QA rows whose evidence is no longer current, with the reason: a criterion revision, an artifact or an attempt that changed.

    Rows that name only apps in `skip_apps` (released apps keep their rows as history) are left out.
    """

    entries = list(history)
    skipped = set(skip_apps)
    current = {criterion.number: criterion for criterion in criteria if criterion.number is not None}
    artifacts = {row.app: clean_cell(row.artifact) for row in evidence.delivery}
    stale: list[tuple[QaRow, str]] = []
    for row in evidence.qa:
        if all(app in skipped for app in row.apps):
            continue
        reason: str | None = None
        for ref in row.criteria:
            criterion = current.get(ref.number)
            if criterion is None or criterion.revision is None:
                reason = f"it cites `AC-{ref.number}`, which is no longer a criterion"
            elif criterion.revision != ref.revision:
                reason = f"it cites `AC-{ref.number}` at a revision that has changed"
            elif row.integration != criterion.integration or (criterion.applies_to and not set(row.apps) <= set(criterion.applies_to)):
                reason = f"`AC-{ref.number}` does not apply to this row"
            if reason:
                break
        if reason is None:
            for app, artifact in row.artifacts.items():
                if app in artifacts and artifacts[app] != artifact:
                    reason = f"it verified `{artifact}` of `{app}`, which is no longer its delivered artifact"
                    break
        if reason is None:
            expected = max(qa_attempt(app, entries) for app in row.apps)
            if row.attempt is not None and row.attempt != expected:
                reason = f"its attempt qa-{row.attempt} is not the current attempt qa-{expected}"
        if reason:
            stale.append((row, reason))
    return stale


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


_INTAKE_ITEM_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)$")


def intake_item_name_problem(name: str) -> str | None:
    """Why `name` is not a `YYYY-MM-DD-slug` intake item name, or ``None`` when it is one.

    The date is the day the source was captured and must be a real calendar day;
    the slug is lowercase words joined by single hyphens.
    """

    match = _INTAKE_ITEM_NAME.match(name)
    if match is None:
        return "an intake item folder is named `YYYY-MM-DD-slug`: a date, then lowercase words joined by single hyphens, such as `2026-10-06-client-call`."
    if parse_iso_date(match.group(1)) is None:
        return f"`{match.group(1)}` is not a calendar date; an intake item folder is named `YYYY-MM-DD-slug`."
    return None


CONFLICT_STATUSES = ("open", "resolved")
CONFLICT_CLAIM_SECTIONS = ("Existing claim", "Incoming claim")
CONFLICT_CLAIM_FIELDS = ("Claim", "Scope", "Evidence")
_BOLD_RUN_IN = r"^\s*(?:[-*+]\s+)?\*\*{label}:\*\*[ \t]*(.*)$"
_LINK_OR_URL = re.compile(r"\[[^\]]+\]\(\s*<?[^)\s>]+|https?://\S+")


def parse_conflict_report(text: str) -> tuple[str | None, list[str]]:
    """Check a `CONFLICT.md` against the format `SCHEMA.md` defines.

    Returns its `status` (``None`` when the front matter has no valid one) and the
    structural problems, each one sentence. The check is mechanical: it never
    judges whether the two claims really contradict each other.
    """

    page = parse_markdown_text(Path("CONFLICT.md"), text)
    if page.parse_errors:
        return None, list(page.parse_errors)
    problems: list[str] = []
    status = page.frontmatter.get("status")
    if not isinstance(status, str) or status not in CONFLICT_STATUSES:
        problems.append("front matter `status` must be `open` or `resolved`.")
        status = None
    for heading in CONFLICT_CLAIM_SECTIONS:
        section = section_text(page.body, heading)
        if not section.strip():
            problems.append(f"the `## {heading}` section is missing or empty.")
            continue
        for label in CONFLICT_CLAIM_FIELDS:
            values = [
                match.group(1).strip()
                for line in section.splitlines()
                if (match := re.match(_BOLD_RUN_IN.format(label=label), line))
            ]
            if not any(values):
                problems.append(f"`## {heading}` needs a `**{label}:**` item with text.")
            elif label == "Evidence" and not any(_LINK_OR_URL.search(value) for value in values):
                problems.append(f"`## {heading}` needs a link in its `**Evidence:**` item.")
    if status == "resolved" and not section_text(page.body, "Resolution").strip():
        problems.append("a `resolved` conflict needs a non-empty `## Resolution` section.")
    return status, problems


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


# Front matter fields that say when a page was written, decided, verified or
# amended. That is history: it lives in log.md, never on a current-state page.
# Names are compared in lower case with `_` read as `-`.
HISTORY_DATE_FIELDS = frozenset(
    {
        "introduced",
        "last-updated",
        "last-modified",
        "last-verified",
        "created",
        "updated",
        "modified",
        "verified",
        "reviewed",
        "date",
        "date-created",
        "date-updated",
        "date-modified",
        "date-verified",
    }
)


def history_date_fields(page: MarkdownPage) -> list[str]:
    """The front matter keys of a page that are history-date fields, as written, in file order."""

    return [
        key
        for key in page.frontmatter
        if isinstance(key, str) and key.strip().casefold().replace("_", "-") in HISTORY_DATE_FIELDS
    ]


def parse_status_board_rows(board_path: Path) -> tuple[list[StatusBoardRow], list[str]]:
    """The feature rows of `status-board.md` and the problems that keep the table from being read.

    The feature table ends at the first line that is not a table row; a table below it (the bugs and operations tables)
    is not read here.
    """

    try:
        text = board_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [], [f"Unable to read status-board.md: {exc}"]

    rows: list[StatusBoardRow] = []
    errors: list[str] = []
    in_feature_table = False
    header_seen = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            if in_feature_table:
                in_feature_table = False
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells == list(STATUS_BOARD_COLUMNS):
            in_feature_table = True
            header_seen = True
            continue
        if not in_feature_table:
            continue
        if _is_separator_row(cells):
            continue
        if len(cells) != len(STATUS_BOARD_COLUMNS):
            errors.append(f"status-board.md contains a feature row with {len(cells)} cells; the table has {len(STATUS_BOARD_COLUMNS)} columns.")
            continue
        feature_id, title, status, owner, advisory_review, design_tracks, app_stages, open_bugs = cells
        if not feature_id:
            errors.append("status-board.md contains a feature row with an empty ID.")
            continue
        rows.append(
            StatusBoardRow(
                feature_id=feature_id,
                title=title,
                status=status,
                owner=owner,
                advisory_review=advisory_review,
                path=board_path,
                design_tracks=design_tracks,
                app_stages=app_stages,
                open_bugs=open_bugs,
            )
        )

    if not header_seen:
        errors.append("status-board.md is missing the feature status board table.")
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
