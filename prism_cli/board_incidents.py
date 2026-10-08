"""The incident half of the board service: the incident record validator (CONTRACTS 6.2, 6.3).

`IncidentActionsMixin` is mixed into `BoardService`. An incident is a dated record that `ingest` writes, and there is no
incident engine: this module checks that a write keeps the record's shape and changes it only where
`incidents/_FORMAT.md` allows. A new incident has a free ID and is never rewritten in its identity (title, date, severity,
apps). An existing one changes by a status step, appended Timeline lines, added follow-ups and releases, and, while it is not
`resolved`, a new Cause, Mitigation, Resolution or Follow-ups section. A new Cause adds a Timeline line that cites the
intake item the cause came from.

Like `board_bugs`, it reaches the helpers of `board_service` through `bs`, which resolves them when a method runs.
"""

from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from typing import Any, Mapping

from prism_cli.board_bugs import bs
from prism_cli.wiki_bugs import BUG_ID_PATTERN, FEATURE_ID_PATTERN
from prism_cli.wiki_incidents import (
    INCIDENT_FIELDS,
    INCIDENT_FILE_PATTERN,
    INCIDENT_ID_PATTERN,
    INCIDENT_SEVERITIES,
    INCIDENT_STATUSES,
    is_incident_path,
    read_incident_pages,
    section_changed,
    section_is_blank,
    section_layout_problem,
    timeline_items,
)
from prism_cli.wiki_model import MARKDOWN_LINK_PATTERN, RELEASE_ID_PATTERN, parse_iso_date, read_release_records

# The incident sections that stay as they are once the incident is `resolved`: the record of how it ended.
_FROZEN_WHEN_RESOLVED = ("Impact", "Cause", "Mitigation", "Resolution")
# The front matter an update never changes (CONTRACTS 6.2).
_IDENTITY_FIELDS = ("id", "title", "date", "severity", "apps")
# The lists an update only adds to.
_ADD_ONLY_FIELDS = ("releases", "follow-ups")


def _quoted(values: Any) -> str:
    return ", ".join(f"`{value}`" for value in values)


class IncidentActionsMixin:
    """Incident page validation for `BoardService`."""

    def _incident_error(self, code: str, message: str, relative: str, **details: Any) -> Any:
        return bs.BoardError(code, message, 409, {"path": relative, **details})

    def _validate_incident_page(
        self,
        relative: str,
        content: str,
        before_text: str | None,
        supplied: Mapping[str, str],
        moves: list[dict[str, Any]],
    ) -> None:
        """The shape of an incident page and, for an existing page, the changes `ingest` may make to it."""

        frontmatter, body = bs._parse_markdown(content, relative)
        error = self._incident_error
        unknown = sorted(set(frontmatter) - set(INCIDENT_FIELDS))
        if unknown:
            raise error("invalid_incident", f"Incident `{relative}` carries only {_quoted(INCIDENT_FIELDS)}; remove {_quoted(unknown)}.", relative, fields=unknown)
        missing = [key for key in INCIDENT_FIELDS if key not in frontmatter]
        if missing:
            raise error("invalid_incident", f"Incident `{relative}` needs the front matter field(s) {_quoted(missing)}.", relative, fields=missing)
        incident_id = frontmatter["id"]
        name = PurePosixPath(relative).name
        match = INCIDENT_FILE_PATTERN.match(name)
        if not isinstance(incident_id, str) or not INCIDENT_ID_PATTERN.match(incident_id) or match is None or match.group(1).casefold() != incident_id.casefold():
            raise error(
                "invalid_incident",
                f"Incident `{relative}` needs `id: INC-<n>` and the file name `INC-<n>-<slug>.md` with the same number and a lowercase hyphenated slug.",
                relative,
            )
        if not isinstance(frontmatter["title"], str) or not frontmatter["title"].strip():
            raise error("invalid_incident", f"Incident `{relative}` needs a nonblank `title`.", relative)
        if parse_iso_date(frontmatter["date"]) is None:
            raise error("invalid_incident", f"Incident `{relative}` needs an ISO `date` (YYYY-MM-DD): the day the incident began.", relative)
        if frontmatter["status"] not in INCIDENT_STATUSES:
            raise error("invalid_incident", f"Incident `{relative}`: `status` is one of {_quoted(INCIDENT_STATUSES)}.", relative, allowed=list(INCIDENT_STATUSES))
        if frontmatter["severity"] not in INCIDENT_SEVERITIES:
            raise error("invalid_incident", f"Incident `{relative}`: `severity` is one of {_quoted(INCIDENT_SEVERITIES)}.", relative, allowed=list(INCIDENT_SEVERITIES))
        apps = frontmatter["apps"]
        known = {app.id for app in self._model.apps} if self._model is not None else set(self._app_ids)  # type: ignore[attr-defined]
        if not isinstance(apps, list) or not apps or any(not isinstance(item, str) for item in apps) or len(set(apps)) != len(apps) or any(item not in known for item in apps):
            raise error(
                "invalid_incident",
                f"Incident `{relative}`: `apps` is a non-empty list of distinct apps of this workspace ({_quoted(sorted(known)) or 'none'}).",
                relative,
                board_apps=sorted(known)[:20],
            )
        releases, follow_ups = frontmatter["releases"], frontmatter["follow-ups"]
        for key, value, patterns, example in (
            ("releases", releases, (RELEASE_ID_PATTERN,), "REL-003"),
            ("follow-ups", follow_ups, (BUG_ID_PATTERN, FEATURE_ID_PATTERN), "BUG-003` or `F-004"),
        ):
            if not isinstance(value, list) or any(not isinstance(item, str) or not any(pattern.match(item) for pattern in patterns) for item in value) or len(set(value)) != len(value):
                raise error("invalid_incident", f"Incident `{relative}`: `{key}` is a list of distinct IDs such as `{example}`, or `[]`.", relative)
        recorded = {record.release_id.casefold() for record in read_release_records(self._wiki_path())}  # type: ignore[attr-defined]
        unknown_releases = [item for item in releases if item.casefold() not in recorded]
        if unknown_releases:
            raise error(
                "incident_release_unknown",
                f"Incident `{relative}` names {_quoted(unknown_releases)}, which {'has' if len(unknown_releases) == 1 else 'have'} no record in `releases/`.",
                relative,
                releases=unknown_releases,
            )
        layout = section_layout_problem(body)
        if layout is not None:
            raise error("invalid_incident", f"Incident `{relative}`: {layout}.", relative)
        for heading in ("Impact", "Cause"):
            if section_is_blank(body, heading):
                hint = " or start it with `**Unknown:**` while the cause is not known" if heading == "Cause" else ""
                raise error("invalid_incident", f"Incident `{relative}` has an empty `## {heading}`; say what it holds{hint}.", relative)
        lines, malformed = timeline_items(body)
        if not lines or malformed:
            raise error(
                "invalid_incident",
                f"Incident `{relative}`: `## Timeline` has one `- YYYY-MM-DD[ HH:MM]: what happened` line per event"
                + (f"; fix {_quoted(line[:60] for line in malformed[:3])}." if malformed else "."),
                relative,
            )
        status = frontmatter["status"]
        if status == "mitigated" and section_is_blank(body, "Mitigation"):
            raise error("invalid_incident", f"Incident `{relative}` is `mitigated` and needs its `## Mitigation` filled in.", relative)
        if status == "resolved" and section_is_blank(body, "Resolution"):
            raise error("invalid_incident", f"Incident `{relative}` is `resolved` and needs its `## Resolution` filled in.", relative)
        bs._validate_no_placeholders(body, relative)
        if before_text is None:
            self._assert_incident_id_free(relative, incident_id, supplied)
        else:
            self._validate_incident_update(relative, frontmatter, body, before_text, moves)

    def _assert_incident_id_free(self, relative: str, incident_id: str, supplied: Mapping[str, str]) -> None:
        taken = [incident for incident in read_incident_pages(self._wiki_path()) if incident.incident_id.casefold() == incident_id.casefold()]  # type: ignore[attr-defined]
        twins = [
            path
            for path, text in supplied.items()
            if path != relative and is_incident_path(path) and str(bs._parse_markdown(text, path)[0].get("id", "")).casefold() == incident_id.casefold()
        ]
        if taken or twins:
            where = taken[0].page.path.relative_to(self.root).as_posix() if taken else twins[0]  # type: ignore[attr-defined]
            raise self._incident_error(
                "incident_id_taken", f"`{incident_id}` is already used by `{where}`; take the next free incident number.", relative, incident_id=incident_id
            )

    def _validate_incident_update(self, relative: str, frontmatter: Mapping[str, Any], body: str, before_text: str, moves: list[dict[str, Any]]) -> None:
        """What ingest may change on an existing incident: a status step, appended Timeline lines, added follow-ups and releases,
        and the Cause, Mitigation, Resolution and Follow-ups sections while the incident is not `resolved`."""

        old_frontmatter, old_body = bs._parse_markdown(before_text, relative)
        error = self._incident_error
        changed_identity = [key for key in _IDENTITY_FIELDS if old_frontmatter.get(key) != frontmatter.get(key)]
        if changed_identity:
            raise error(
                "incident_frontmatter_scope",
                f"Incident `{relative}` is a record: ingest cannot change {_quoted(changed_identity)}. It changes `status`, adds to `releases` and `follow-ups`, and appends Timeline lines.",
                relative,
                fields=changed_identity,
            )
        for key in _ADD_ONLY_FIELDS:
            dropped = [item for item in old_frontmatter.get(key) or [] if item not in frontmatter.get(key, [])]
            if dropped:
                raise error("incident_frontmatter_scope", f"Incident `{relative}`: `{key}` only gains entries; it cannot drop {_quoted(dropped)}.", relative, fields=[key])
        old_status, new_status = old_frontmatter.get("status"), frontmatter.get("status")
        resolved = old_status == "resolved"
        if resolved and new_status != "resolved":
            raise error(
                "incident_resolved_final",
                f"Incident `{relative}` is `resolved`. A recurrence is a new incident; ingest cannot reopen this record.",
                relative,
            )
        if section_changed(old_body, body, "Impact"):
            raise error("incident_body_scope", f"Incident `{relative}`: ingest cannot change `## Impact`; it is the record of what happened.", relative, section="Impact")
        old_lines, _ = timeline_items(old_body)
        new_lines, _ = timeline_items(body)
        if new_lines[: len(old_lines)] != old_lines:
            raise error(
                "incident_timeline_not_append_only",
                f"Incident `{relative}`: `## Timeline` only gains lines at its end; earlier lines stay as they were.",
                relative,
            )
        if resolved:
            frozen = [heading for heading in _FROZEN_WHEN_RESOLVED if section_changed(old_body, body, heading)]
            added_follow_up = set(frontmatter.get("follow-ups", [])) != set(old_frontmatter.get("follow-ups") or [])
            if section_changed(old_body, body, "Follow-ups") and not added_follow_up:
                frozen.append("Follow-ups")
            if frozen:
                raise error(
                    "incident_body_scope",
                    f"Incident `{relative}` is `resolved`: ingest cannot change {_quoted(f'## {heading}' for heading in frozen)}. "
                    "It appends Timeline lines and adds follow-ups and releases.",
                    relative,
                    sections=frozen,
                )
        if section_changed(old_body, body, "Cause"):
            self._assert_cause_cited(relative, old_lines, new_lines, moves)

    def _assert_cause_cited(self, relative: str, old_lines: list[str], new_lines: list[str], moves: list[dict[str, Any]]) -> None:
        """A changed Cause adds a Timeline line that links the intake item the proposal processes (CONTRACTS 6.2)."""

        destination = str(moves[0]["destination"]).rstrip("/") if moves else ""
        for line in new_lines[len(old_lines):]:
            for match in MARKDOWN_LINK_PATTERN.finditer(line):
                target = (match.group(1) or match.group(2) or "").split("#", 1)[0]
                if not target or "://" in target:
                    continue
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
                if destination and (resolved == destination or resolved.startswith(destination + "/")):
                    return
        raise self._incident_error(
            "incident_cause_uncited",
            f"Incident `{relative}`: a new Cause adds a `## Timeline` line that links the intake item it came from"
            + (f" (`{destination}`)" if destination else "")
            + ", for example `- 2026-10-09: Cause recorded ([intake item](../../intake/processed/2026-10-09-slug/MANIFEST.md))`.",
            relative,
        )
