"""A synthetic graph envelope with bug, release and incident records, for the board page's record views.

The records follow the shape the graph carries in ``facts.bugs``, ``facts.releases`` and ``facts.incidents``: every key
is present and an optional value is ``null``. Together they cover every bug status, severity, flag and disposition, every
release kind and outcome (a chain of retry and rollback, the current delivery and an invalid record), every incident
status (a cause that is unknown, a timeline cut to its last lines, an invalid page) and hostile text in the fields a
person writes.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from prism_cli.wiki_graph import action_registry

HOSTILE_TITLE = "<img src=x onerror=alert(1)>"
HOSTILE_APP = "<svg/onload=alert(2)>"


def _bug(number: int, title: str, status: str, **fields: Any) -> dict[str, Any]:
    identifier = f"BUG-{number:03d}"
    record: dict[str, Any] = {
        "id": identifier,
        "title": title,
        "path": f"knowledge/wiki/bugs/{identifier}-{title.lower().replace(' ', '-')[:30]}.md",
        "status": status,
        "owner": "dev",
        "severity": "medium",
        "blocking": False,
        "apps": ["backend"],
        "feature": None,
        "found_in": None,
        "environment": None,
        "deferred": False,
        "close_reason": None,
        "duplicate_of": None,
        "promoted_to": None,
        "regression_of": None,
        "summary": None,
        "fix": [],
        "verification": [],
        "release": [],
        "valid": True,
    }
    record.update(fields)
    return record


def _release(number: int, title: str, date: str, kind: str, outcome: str, **fields: Any) -> dict[str, Any]:
    identifier = f"REL-{number:03d}"
    record: dict[str, Any] = {
        "id": identifier,
        "title": title,
        "path": f"knowledge/wiki/releases/{identifier}.md",
        "date": date,
        "kind": kind,
        "outcome": outcome,
        "features": [],
        "bugs": [],
        "retry_of": None,
        "rollback_of": None,
        "summary": None,
        "deliveries": [],
        "current": False,
        "valid": True,
    }
    record.update(fields)
    return record


def _incident(number: int, title: str, status: str, **fields: Any) -> dict[str, Any]:
    identifier = f"INC-{number:03d}"
    record: dict[str, Any] = {
        "id": identifier,
        "title": title,
        "path": f"knowledge/wiki/incidents/{identifier}-{title.lower().replace(' ', '-')[:30]}.md",
        "date": "2026-10-09",
        "status": status,
        "severity": "medium",
        "apps": ["backend"],
        "releases": [],
        "follow_ups": [],
        "impact": None,
        "cause_known": True,
        "timeline": [],
        "timeline_truncated": False,
        "valid": True,
    }
    record.update(fields)
    return record


def _delivery(item: str, app: str, target: str, version: str, attempt: str, outcome: str) -> dict[str, str]:
    return {"item": item, "app": app, "target": target, "version": version, "attempt": attempt, "outcome": outcome}


def _by_number(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every list of the graph is sorted by record number, ascending."""

    return sorted(records, key=lambda record: int(record["id"].rsplit("-", 1)[1]))


def _bugs() -> list[dict[str, Any]]:
    return _by_number([
        _bug(1, "Summary lacks the hidden comment count", "open", severity="critical", blocking=True, feature="F-001", found_in="build:backend#88", environment="staging",
             summary="The summary shows the visible comments only, so a reviewer cannot tell that some are hidden."),
        _bug(2, "Export drops right-to-left text", "in-fix", severity="high", apps=["backend", "web"], feature="F-001", deferred=True),
        _bug(3, "Reviewer list flickers on refresh", "fixed", owner="qa", apps=["web"], regression_of="BUG-004",
             fix=[{"app": "web", "artifact": "commit:91ab3c2"}],
             verification=[{"app": "web", "attempt": "qa-1", "result": "blocked"}]),
        _bug(4, "Timeout on a long document", "verified", owner="release", severity="low", feature="F-002",
             fix=[{"app": "backend", "artifact": "commit:5d7a1e4"}],
             verification=[{"app": "backend", "attempt": "qa-1", "result": "fail"}, {"app": "backend", "attempt": "qa-2", "result": "pass"}]),
        _bug(5, "Wrong locale in the sign-in mail", "released", owner="none", severity="high", feature="F-002",
             fix=[{"app": "backend", "artifact": "commit:77c0de1"}], verification=[{"app": "backend", "attempt": "qa-3", "result": "pass"}],
             release=[{"app": "backend", "target": "production", "outcome": "released", "record": "REL-002"},
                      {"app": "web", "target": "production", "outcome": "pending", "record": None}]),
        _bug(6, "Cosmetic misalignment of the footer", "closed", owner="none", severity="low", close_reason="wont-fix"),
        _bug(7, "Export drops RTL text again", "closed", owner="none", severity="high", close_reason="duplicate", duplicate_of="BUG-002"),
        _bug(8, "Add an audit trail to the export", "closed", owner="none", close_reason="promoted", promoted_to="F-002"),
        # An invalid page can carry a null where a valid one never does.
        _bug(9, "Page with no status", None, owner=None, severity=None, blocking=None, valid=False,
             fix=[{"app": "backend", "artifact": None}],
             verification=[{"app": "backend", "attempt": None, "result": None}],
             release=[{"app": "backend", "target": None, "outcome": None, "record": None}]),
        _bug(11, "Page with a status the lifecycle does not know", "triaged", owner="none", severity=None, valid=False),
        _bug(12, "A very long title that the data does not bound " + "and keeps going " * 14, "open",
             fix=[{"app": "backend", "artifact": "commit:" + "0123456789abcdef" * 12}]),
        _bug(10, HOSTILE_TITLE, "open", apps=[HOSTILE_APP], environment="<b>prod</b>", found_in='build:"><i>#1</i>', summary="<script>alert(3)</script>",
             fix=[{"app": HOSTILE_APP, "artifact": "commit:<u>x</u>"}]),
    ])


def _releases() -> list[dict[str, Any]]:
    return _by_number([
        _release(1, "Review summary export", "2026-10-02", "release", "failed", features=["F-001"],
                 deliveries=[_delivery("F-001", "backend", "production", "build:backend#400", "release-1", "failed")]),
        _release(2, "Review summary export, retry", "2026-10-09", "retry", "released", features=["F-001"], bugs=["BUG-005"], retry_of="REL-001", current=True,
                 summary="The retry shipped after the migration was fixed.",
                 deliveries=[_delivery("F-001", "backend", "production", "build:backend#412", "release-2", "released"),
                             _delivery("BUG-005", "web", "staging", "build:web#31", "release-2", "released")]),
        _release(3, "Roll back the export", "2026-10-10", "rollback", "rolled-back", features=["F-001"], rollback_of="REL-002",
                 deliveries=[_delivery("F-001", "backend", "production", "build:backend#400", "rollback-1", "rolled-back")]),
        _release(4, "Redeploy the web app", "2026-10-11", "redeploy", "partial", features=["F-002"], current=True,
                 deliveries=[_delivery("F-002", "web", "production", "build:web#33", "redeploy-1", "released"),
                             _delivery("F-002", "backend", "staging", "build:backend#415", "redeploy-1", "failed")]),
        _release(6, "Redeploy the backend", "2026-10-12", "redeploy", "failed", features=["F-002"],
                 deliveries=[_delivery("F-002", "backend", "production", "build:backend#416", "redeploy-2", "failed")]),
        _release(7, "Record with a missing date and outcome", None, "release", None, valid=False,
                 deliveries=[{"item": "F-002", "app": "backend", "target": "production", "version": "build:backend#" + "9" * 100, "attempt": "release-1", "outcome": None}]),
        _release(5, HOSTILE_TITLE, "2026-09-30", "release", "released", valid=False, features=["F-002"],
                 deliveries=[_delivery("F-002", "backend", "production", "<i>v1</i>", "release-1", "released")]),
    ])


def _incidents() -> list[dict[str, Any]]:
    long_timeline = [{"when": f"2026-10-09 10:{minute:02d}", "text": f"Timeline line {minute}"} for minute in range(20)]
    return _by_number([
        _incident(1, "Blank summary for right-to-left comments", "open", severity="critical", releases=["REL-002"], follow_ups=["BUG-002", "F-001"],
                  impact="Reviewers saw a blank summary for every document with right-to-left comments.", cause_known=False,
                  timeline=[{"when": "2026-10-09 09:10", "text": "Support reported the blank summary."}, {"when": "2026-10-09 09:40", "text": "The export was identified as the source."}]),
        _incident(2, "Slow exports after the retry", "mitigated", severity="high", apps=["backend", "web"], releases=["REL-002", "REL-003"], follow_ups=["BUG-004"],
                  impact="Exports took more than a minute for large documents.", timeline=long_timeline, timeline_truncated=True),
        _incident(3, "Stale cache after a rollback", "resolved", severity="low", date="2026-10-04", releases=["REL-001"]),
        _incident(5, "Page with no status, date or severity", None, date=None, severity=None, valid=False),
        _incident(4, HOSTILE_TITLE, "open", severity="medium", apps=[HOSTILE_APP], impact="<script>alert(5)</script>", valid=False, follow_ups=["BUG-404"],
                  timeline=[{"when": "<b>now</b>", "text": "<img src=x onerror=alert(6)>"}]),
    ])


def _feature(identifier: str, title: str, status: str, owner: str, slug: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "type": "feature",
        "title": title,
        "path": f"knowledge/wiki/features/{identifier}-{slug}.md",
        "health": "ok",
        "status": status,
        "owner": owner,
        "advisory_review": "not-needed",
        "open_questions": [],
    }


def records_envelope(root: Path) -> dict[str, Any]:
    """An envelope of two features and two apps with the records above."""

    features = [
        _feature("F-001", "Review summary export", "in-qa", "qa", "review-summary-export"),
        _feature("F-002", "Document audit trail", "released", "none", "document-audit-trail"),
    ]
    apps = [
        {"id": "app:backend", "type": "app", "title": "backend", "path": None, "health": "ok", "status": "active"},
        {"id": "app:web", "type": "app", "title": "web", "path": None, "health": "ok", "status": "active"},
    ]
    edges = [
        {"source": feature["id"], "target": app["id"], "kind": "targets", "evidence": "frontmatter apps"}
        for feature in features
        for app in apps
    ]
    return {
        "schema_version": 1,
        "experimental": True,
        "command": "wiki graph",
        "root": str(root),
        "generated_at": "2026-10-13T12:00:00+02:00",
        "confidence": "high",
        "workspace": {"kind": "generated-project", "project_name": "Records fixture", "apps": [{"id": "backend"}, {"id": "web"}]},
        "facts": {
            "node_count": len(features) + len(apps),
            "edge_count": len(edges),
            "nodes": features + apps,
            "edges": edges,
            "dangling_references": [],
            "setup_state": "initialized",
            "intake": {"pending": [], "quarantined": []},
            "action_registry": action_registry(),
            "app_operations": [
                {"app": "backend", "delivery_target": "production", "released_features": "F-002", "latest_release": "REL-006", "latest_outcome": "failed",
                 "open_bugs": "BUG-001, BUG-002, BUG-010", "open_incidents": "INC-001, INC-002"},
                {"app": "web", "delivery_target": "production", "released_features": "—", "latest_release": "REL-004", "latest_outcome": "released",
                 "open_bugs": "BUG-003", "open_incidents": "INC-002"},
            ],
            "bugs": _bugs(),
            "releases": _releases(),
            "incidents": _incidents(),
        },
        "blocker_facts": [],
        "required_obligations": [],
        "sources": [],
        "diagnostics": [],
    }


def without_records(envelope: dict[str, Any]) -> dict[str, Any]:
    """The same envelope with no bug, release or incident record."""

    bare = copy.deepcopy(envelope)
    for key in ("bugs", "releases", "incidents"):
        bare["facts"][key] = []
    bare["facts"]["app_operations"] = []
    return bare
