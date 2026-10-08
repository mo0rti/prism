"""The incident record of the wiki: its fields, its timeline and its lint (CONTRACTS 6.2).

An incident lives in `knowledge/wiki/incidents/INC-XXX-slug.md`. It is a dated record that `ingest` writes: it states the
impact, the timeline, the cause, the mitigation, the resolution and the follow-ups of one incident, and it changes only
where `incidents/_FORMAT.md` allows (a status step, appended Timeline lines, added follow-ups and releases, and the
Cause, Mitigation, Resolution and Follow-ups sections while the incident is not `resolved`). There is no incident engine:
the board validates the write, and this module reads the page and answers the questions the status board and lint ask.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from prism_cli.wiki_bugs import BUG_ID_PATTERN, BUG_SEVERITIES, FEATURE_ID_PATTERN
from prism_cli.wiki_model import (
    RELEASE_ID_PATTERN,
    MarkdownPage,
    normalize_feature_id,
    parse_iso_date,
    read_markdown_pages,
    section_text,
)

INCIDENT_DIRECTORY = "incidents"
INCIDENT_DIRECTORY_PREFIX = "knowledge/wiki/incidents/"
INCIDENT_ID_PATTERN = re.compile(r"^INC-(\d+)$")
INCIDENT_FILE_PATTERN = re.compile(r"^(INC-\d+)-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
INCIDENT_STATUSES = ("open", "mitigated", "resolved")
# The statuses of an incident that is not over: the status board lists it as open.
OPEN_INCIDENT_STATUSES = ("open", "mitigated")
INCIDENT_SEVERITIES = BUG_SEVERITIES
INCIDENT_FIELDS = ("id", "title", "date", "status", "severity", "apps", "releases", "follow-ups")
INCIDENT_SECTIONS = ("Impact", "Timeline", "Cause", "Mitigation", "Resolution", "Follow-ups")
# `- YYYY-MM-DD[ HH:MM[ Z|UTC|+HH:MM]]: what happened`.
TIMELINE_LINE = re.compile(r"^[-*+]\s+(?P<date>\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2}(?:\s*(?:Z|UTC|[+-]\d{2}:?\d{2}))?)?:\s+(?P<text>\S.*)$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_UNKNOWN_LABEL = re.compile(r"^\*\*Unknown:\*\*", re.IGNORECASE)


def is_incident_path(relative: str) -> bool:
    return relative.startswith(INCIDENT_DIRECTORY_PREFIX)


def section_is_blank(body: str, heading: str) -> bool:
    """Whether a section holds no content: only whitespace and HTML comments."""

    return not _COMMENT.sub("", section_text(body, heading)).strip()


def timeline_items(body: str) -> tuple[list[str], list[str]]:
    """The lines of `## Timeline` as written, and the lines that are not `- YYYY-MM-DD[ HH:MM]: text` entries.

    Blank lines and HTML comments are not lines of the timeline.
    """

    lines: list[str] = []
    malformed: list[str] = []
    for raw in _COMMENT.sub("", section_text(body, "Timeline")).splitlines():
        line = raw.strip()
        if not line:
            continue
        lines.append(line)
        match = TIMELINE_LINE.match(line)
        if match is None or _bad_date(match.group("date")):
            malformed.append(line)
    return lines, malformed


def _bad_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return True
    return False


_HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def section_layout_problem(body: str) -> str | None:
    """Why the body is not the six sections of `incidents/_FORMAT.md` in order with nothing above them, or ``None``."""

    headings: list[str] = []
    preamble: list[str] = []
    in_fence = False
    for raw in body.splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(raw.strip())
        if match is not None:
            headings.append(match.group(1).strip())
        elif not headings:
            preamble.append(raw)
    if _COMMENT.sub("", "\n".join(preamble)).strip():
        return "the page has text above `## Impact`; an incident page holds only its six sections"
    if headings != list(INCIDENT_SECTIONS):
        listed = ", ".join(f"`## {heading}`" for heading in INCIDENT_SECTIONS)
        return f"the sections must be {listed}, each once and in that order"
    return None


def cause_is_unknown(body: str) -> bool:
    """Whether `## Cause` says the cause is not known yet: it starts with the `**Unknown:**` label."""

    text = _COMMENT.sub("", section_text(body, "Cause")).strip()
    return bool(_UNKNOWN_LABEL.match(text))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", _COMMENT.sub("", text)).strip()


def section_changed(old_body: str, new_body: str, heading: str) -> bool:
    return _normalized(section_text(old_body, heading)) != _normalized(section_text(new_body, heading))


@dataclass(frozen=True)
class IncidentPage:
    """An incident page read from the wiki. Missing or malformed fields read as ``None`` or empty; lint reports them."""

    page: MarkdownPage

    def _text(self, key: str) -> str | None:
        value = self.page.frontmatter.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _list(self, key: str) -> list[str]:
        value = self.page.frontmatter.get(key)
        return [item.strip() for item in value if isinstance(item, str)] if isinstance(value, list) else []

    @property
    def incident_id(self) -> str:
        value = self._text("id")
        if value is not None:
            return value
        match = re.match(r"^(INC-\d+)(?:-|$)", self.page.path.stem)
        return match.group(1) if match else self.page.path.stem

    @property
    def number(self) -> int:
        match = INCIDENT_ID_PATTERN.match(self.incident_id)
        return int(match.group(1)) if match else 0

    @property
    def title(self) -> str:
        return self._text("title") or self.page.path.stem

    @property
    def status(self) -> str | None:
        return self._text("status")

    @property
    def severity(self) -> str | None:
        return self._text("severity")

    @property
    def date(self) -> date | None:
        return parse_iso_date(self.page.frontmatter.get("date"))

    @property
    def apps(self) -> list[str]:
        return self._list("apps")

    @property
    def releases(self) -> list[str]:
        return self._list("releases")

    @property
    def follow_ups(self) -> list[str]:
        return self._list("follow-ups")

    @property
    def open(self) -> bool:
        """Whether the incident is not `resolved`: the status board lists it under the apps it names."""

        return self.status != "resolved"


def read_incident_pages(wiki_root: Path) -> list[IncidentPage]:
    """Every incident page of a wiki, in file order."""

    return [IncidentPage(page) for page in read_markdown_pages(wiki_root / INCIDENT_DIRECTORY)]


def incident_sort_key(incident_id: str) -> tuple[int, str]:
    match = INCIDENT_ID_PATTERN.match(incident_id)
    return (int(match.group(1)) if match else 10**9, incident_id)


# --- Lint ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IncidentFinding:
    code: str
    severity: str
    path: Path
    message: str


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"`{value}`" for value in values)


def lint_incident_page(
    incident: IncidentPage,
    *,
    app_ids: set[str],
    release_ids: set[str],
    bug_ids: set[str],
    feature_ids: set[str],
) -> list[IncidentFinding]:
    """The findings for one incident page.

    `release_ids`, `bug_ids` and `feature_ids` hold the casefolded IDs of the records, bugs and features of the wiki.
    A shape problem is `incident-record-invalid` (error); a follow-up that names no bug or feature page is
    `incident-follow-up-missing` (warning), because the page it will name may not be written yet.
    """

    path = incident.page.path
    frontmatter = incident.page.frontmatter
    body = incident.page.body
    findings: list[IncidentFinding] = []

    def add(message: str, code: str = "incident-record-invalid", severity: str = "error") -> None:
        findings.append(IncidentFinding(code, severity, path, message))

    for key in frontmatter:
        if key not in INCIDENT_FIELDS:
            add(f"`{key}` is not an incident field; an incident page carries only {_quoted(INCIDENT_FIELDS)}.")
    for key in INCIDENT_FIELDS:
        if key not in frontmatter:
            add(f"Required frontmatter field `{key}` is missing.")
    incident_id = frontmatter.get("id")
    if "id" in frontmatter:
        if not isinstance(incident_id, str) or not INCIDENT_ID_PATTERN.match(incident_id.strip()):
            add("`id` must be an incident ID such as `INC-001`.")
        else:
            file_match = INCIDENT_FILE_PATTERN.match(path.name)
            if file_match is None or file_match.group(1).casefold() != incident_id.strip().casefold():
                add(f"The file name must be `{incident_id.strip()}-<slug>.md` (lowercase words joined by hyphens).")
    if "title" in frontmatter and incident._text("title") is None:
        add("`title` must be a non-empty string.")
    if "date" in frontmatter and incident.date is None:
        add("`date` must be an ISO date such as `2026-10-09`.")
    status = incident.status
    if "status" in frontmatter and status not in INCIDENT_STATUSES:
        add(f"`status` must be one of {_quoted(INCIDENT_STATUSES)}.")
    if "severity" in frontmatter and incident.severity not in INCIDENT_SEVERITIES:
        add(f"`severity` must be one of {_quoted(INCIDENT_SEVERITIES)}.")
    apps_value = frontmatter.get("apps")
    if "apps" in frontmatter:
        if not isinstance(apps_value, list) or not apps_value or any(not isinstance(item, str) for item in apps_value) or len(set(apps_value)) != len(apps_value):
            add("`apps` must be a non-empty list of distinct app IDs.")
        else:
            unknown = [app for app in apps_value if app not in app_ids]
            if unknown:
                add(f"{_quoted(unknown)} {'is' if len(unknown) == 1 else 'are'} not an app of this workspace.")
    releases_value = frontmatter.get("releases")
    if "releases" in frontmatter:
        if not isinstance(releases_value, list) or any(not isinstance(item, str) for item in releases_value) or len(set(releases_value)) != len(releases_value):
            add("`releases` must be a list of distinct release record IDs such as `REL-003`, or `[]`.")
        else:
            malformed = [item for item in releases_value if not RELEASE_ID_PATTERN.match(item.strip())]
            if malformed:
                add(f"`releases` lists {_quoted(malformed)}, which {'is not a release record ID' if len(malformed) == 1 else 'are not release record IDs'} such as `REL-003`.")
            missing = [item for item in releases_value if RELEASE_ID_PATTERN.match(item.strip()) and item.strip().casefold() not in release_ids]
            if missing:
                add(f"`releases` names {_quoted(missing)}, which {'has' if len(missing) == 1 else 'have'} no record in `releases/`.")
    follow_ups_value = frontmatter.get("follow-ups")
    if "follow-ups" in frontmatter:
        if not isinstance(follow_ups_value, list) or any(not isinstance(item, str) for item in follow_ups_value) or len(set(follow_ups_value)) != len(follow_ups_value):
            add("`follow-ups` must be a list of distinct bug or feature IDs such as `BUG-003`, or `[]`.")
        else:
            for item in follow_ups_value:
                text = item.strip()
                if BUG_ID_PATTERN.match(text):
                    known = text.casefold() in bug_ids
                elif FEATURE_ID_PATTERN.match(text):
                    known = normalize_feature_id(text) in feature_ids
                else:
                    add(f"`follow-ups` lists `{text}`, which is not a bug or feature ID such as `BUG-003` or `F-004`.")
                    continue
                if not known:
                    add(f"The follow-up `{text}` names no page of this wiki.", "incident-follow-up-missing", "warning")

    layout = section_layout_problem(body)
    if layout is not None:
        add(f"The page is malformed: {layout}.")
    if section_is_blank(body, "Impact") and re.search(r"(?im)^##\s+Impact\s*#*\s*$", body):
        add("`## Impact` is empty; say who or what the incident affected and how badly.")
    lines, malformed_lines = timeline_items(body)
    if re.search(r"(?im)^##\s+Timeline\s*#*\s*$", body):
        if not lines:
            add("`## Timeline` has no entries; each is `- YYYY-MM-DD[ HH:MM]: what happened`.")
        for line in malformed_lines:
            add(f"The Timeline line `{line[:80]}` is not `- YYYY-MM-DD[ HH:MM]: what happened`.")
    if re.search(r"(?im)^##\s+Cause\s*#*\s*$", body) and section_is_blank(body, "Cause"):
        add("`## Cause` is empty; say what caused the incident, or start with `**Unknown:**` while the cause is not known.")
    if status == "mitigated" and section_is_blank(body, "Mitigation"):
        add("A `mitigated` incident needs its `## Mitigation` filled in.")
    if status == "resolved" and section_is_blank(body, "Resolution"):
        add("A `resolved` incident needs its `## Resolution` filled in.")
    return findings


def lint_incidents(
    incidents: list[IncidentPage],
    *,
    app_ids: set[str],
    release_ids: set[str],
    bug_ids: set[str],
    feature_ids: set[str],
) -> list[IncidentFinding]:
    """Findings for every incident page: the page checks and duplicate IDs."""

    findings: list[IncidentFinding] = []
    seen: dict[str, IncidentPage] = {}
    for incident in incidents:
        findings.extend(lint_incident_page(incident, app_ids=app_ids, release_ids=release_ids, bug_ids=bug_ids, feature_ids=feature_ids))
        key = incident.incident_id.casefold()
        if key in seen:
            findings.append(IncidentFinding("incident-record-invalid", "error", incident.page.path, f"Duplicate incident id `{incident.incident_id}`."))
        seen[key] = incident
    return findings
