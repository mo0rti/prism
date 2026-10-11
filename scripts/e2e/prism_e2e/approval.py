"""Bind a journey approval to the preview the step is allowed to propose."""

from __future__ import annotations

import re
from typing import Any

# A bug or incident page is named by its ID and a slug the agent derives from the title, so the
# fixture's slug is one valid name among many. Any slug is permitted for an ID the fixtures write.
_ID_PAGE = re.compile(r"(knowledge/wiki/(?:bugs|incidents)/(?:BUG|INC)-\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md")


def path_permitted(path: str, permitted: list[str]) -> bool:
    """Whether ``path`` is a permitted write: a fixture path, or a bug or incident page of a fixture ID with another slug."""

    if path in permitted:
        return True
    match = _ID_PAGE.fullmatch(path)
    if match is None:
        return False
    return any((other := _ID_PAGE.fullmatch(candidate)) is not None and other.group(1) == match.group(1) for candidate in permitted)


def check_preview(preview: dict[str, Any], preview_id: str, expected: dict[str, Any]) -> None:
    """Refuse a different action, subject, grant, role predicate or write boundary."""

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(f"The approval preview does not match the step: {message}.")

    require(preview.get("preview_id") == preview_id, "preview ID")
    require(preview.get("action") == expected["action"], "action")
    subject = preview.get("bug_id") or preview.get("feature_id")
    require(subject == expected["item_id"], "feature or bug ID")
    require(preview.get("classification") == "ready" and preview.get("applicable") is True, "applicability")
    approval = preview.get("approval") or {}
    proposer = approval.get("proposer") or {}
    require(proposer.get("kind") == "agent" and proposer.get("participant_id") == expected["proposer_id"], f"proposer {expected['proposer_label']}")
    roles = approval.get("required_roles") or {}
    require(all(sorted(roles.get(key, [])) == sorted(expected["required_roles"][key]) for key in ("all_of", "any_of")), "role predicate")
    writes = preview.get("writes")
    require(isinstance(writes, list) and bool(writes), "exact write set is missing")
    paths: set[str] = set()
    for write in writes:
        require(isinstance(write, dict), "write entry")
        path = write.get("path")
        require(isinstance(path, str) and path_permitted(path, expected["permitted_paths"]) and path not in paths, "write path")
        require("before" in write and isinstance(write.get("after"), str), "write content")
        paths.add(path)
    moves = preview.get("moves", [])
    require(isinstance(moves, list), "move set")
    for move in moves:
        require(isinstance(move, dict) and {"source": move.get("source"), "destination": move.get("destination")} in expected["permitted_moves"], "intake folder move")
