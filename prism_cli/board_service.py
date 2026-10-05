"""Confirmation-gated, provider-neutral service for an adopted Prism board.

Wiki files are the source of truth.  The local journal binds participants,
previews, idempotent operation IDs, and crash recovery to those files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import tempfile
import threading
from typing import Any, Iterable, Iterator, Mapping
from uuid import UUID, uuid4

import yaml

from prism_cli.board_store import BoardLockError, BoardStore
from prism_cli.fs_safety import CLOUD_SYNC_MESSAGE, CloudSyncPathError, reparse_kind
from prism_cli.wiki_model import (
    api_surface_declared,
    is_pending_intake_source,
    processed_source_path,
    section_text,
    source_link_parts,
    within_wiki_read_scope,
)


_MAX_TEXT_FILE = 512 * 1024
_MAX_READ_TOTAL = 2 * 1024 * 1024
_MAX_READ_PATHS = 64
_MCP_CONTRACT = 2
# A path segment every operating system can hold. Windows refuses these characters,
# a trailing dot or space and the device names, so Prism refuses them on every
# system: a workspace written on Linux can then be checked out on Windows.
_WINDOWS_INVALID_CHARACTERS = re.compile(r'[:<>"|?*\x00-\x1f\x7f]')
_WINDOWS_DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))})
_TEXT_FILE_SUFFIXES = (".md", ".txt", ".yaml", ".yml")
_MAX_PREVIEW_CHANGES = 128
_HUMAN_ACTIONS = {"po-handoff", "design-start", "dev-start"}
_SUPPORTED_PLATFORMS = frozenset({"backend", "mobile-android", "mobile-ios", "web-user-app", "web-admin-portal"})
_CANONICAL_MANIFEST_PATHS = {
    "wiki_root": "knowledge/wiki",
    "intake_root": "knowledge/intake",
    "advisory_board": "knowledge/wiki/advisory/BOARD.md",
}
_LIFECYCLE_SKILLS = {
    "po-specify": "po-specify",
    "po-handoff": "po-handoff",
    "design-start": "design-start",
    "design-handoff": "design-handoff",
    "dev-start": "dev-start",
    "dev-done": "dev-done",
    "feature-reopen": None,
}
_DEV_CLARIFY_REQUIREMENT_ORDER = ("What to build", "Technical constraints", "API contract reference", "Acceptance criteria")
_DEV_CLARIFY_REQUIREMENT_SECTIONS = set(_DEV_CLARIFY_REQUIREMENT_ORDER)
_QUESTION_SKILLS = {"po-clarify": "po", "design-clarify": "designer", "dev-clarify": "dev", "ask": None}
_INTAKE_SKILLS = {"po-intake", "design-intake"}
_WRITE_SKILLS = frozenset((*_LIFECYCLE_SKILLS, *_QUESTION_SKILLS, *_INTAKE_SKILLS))
_WIKI_DIRS = (
    "features",
    "personas",
    "business-rules",
    "design",
    "platform-requirements",
    "api-contracts",
    "advisory",
    "decisions",
)
_INDEX_ROW = re.compile(r"^\|\s*(F-\d+)\s*\|\s*(.*?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*$", re.IGNORECASE)
_FRONTMATTER = re.compile(r"\A\ufeff?---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


class BoardError(Exception):
    """A safe, transport-ready service error."""

    def __init__(self, code: str, message: str, status: int = 400, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = _error_details(details)


_MAX_ERROR_DETAILS_CHARS = 1200


def _error_details(details: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a small JSON-safe copy of structured error details, or None."""

    if not isinstance(details, Mapping) or not details:
        return None
    try:
        encoded = json.dumps(dict(details), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None
    if len(encoded) > _MAX_ERROR_DETAILS_CHARS:
        return None
    return json.loads(encoded)


def _clip(value: Any, limit: int) -> str:
    """Collapse whitespace and truncate to at most `limit` characters."""

    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else text[: max(limit - 3, 0)].rstrip() + "..."


def _names(values: Iterable[Any], *, limit: int = 20) -> list[str]:
    """Sorted, clipped field names for an error message or details mapping."""

    return sorted({_clip(value, 60) for value in values})[:limit]


def _quoted(values: Iterable[str]) -> str:
    return ", ".join(f"`{value}`" for value in values)


def _shape_details(
    index: int,
    item: Any,
    expected: tuple[str, ...],
    *,
    string_fields: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    """Describe what is wrong with one change or move item."""

    if not isinstance(item, Mapping):
        problems = [f"is a {type(item).__name__}, not an object"]
        missing, unexpected, wrong_type = list(expected), [], []
    else:
        keys = {str(key) for key in item}
        missing = [name for name in expected if name not in keys]
        unexpected = _names(keys - set(expected))
        wrong_type = [name for name in string_fields if name in item and not isinstance(item[name], str)]
        problems = []
        if missing:
            problems.append(f"is missing {_quoted(missing)}")
        if unexpected:
            problems.append(f"has unexpected field(s) {_quoted(unexpected)}")
        if wrong_type:
            problems.append(f"needs string values for {_quoted(wrong_type)}")
    details: dict[str, Any] = {"index": index, "missing": missing, "unexpected": unexpected, "expected": list(expected)}
    if wrong_type:
        details["not_string"] = wrong_type
    return "; ".join(problems), details


@dataclass(frozen=True)
class Actor:
    participant_id: str
    kind: str
    name: str
    writable: bool
    board_id: str
    workflow_version: str
    scopes: tuple[str, ...]
    _token_hash: str
    _service_proof: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "kind": self.kind,
            "name": self.name,
            "writable": self.writable,
            "board_id": self.board_id,
            "workflow_version": self.workflow_version,
            "scopes": list(self.scopes),
        }


class BoardService:
    """Shared workflow service used by local HTTP, MCP, and CLI adapters."""

    def __init__(self, root: Path) -> None:
        supplied_root = Path(root).expanduser().absolute()
        self._reject_reparse(supplied_root, include_leaf=True)
        try:
            self.root = supplied_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise BoardError("invalid_workspace", "The workspace root cannot be resolved safely.", 400) from exc
        self._lock = threading.RLock()
        # Digests this service returned from read_workspace, per path, so a
        # digest that was never returned can be told from one that went stale.
        self._served_lock = threading.Lock()
        self._served_digests: dict[str, list[str]] = {}
        # The digest each participant last received for the whole of a file
        # from read_workspace, per path. preview_skill uses it for a reviewed
        # source whose revision the proposal leaves out. Memory only: a service
        # restart clears it and the agent reads again.
        self._participant_reads: dict[str, dict[str, tuple[str, str]]] = {}
        self._closed = False
        self._board_id: str | None = None
        self._workflow_version: str | None = None
        self._mode: str | None = None
        self._project_name: str | None = None
        self._platforms: list[str] = []
        self._asset_digest_value: str | None = None
        self._identity_facts: tuple[Any, ...] | None = None
        self._read_only_reason: str | None = None
        self._load_identity()
        if (self.root / "copier.yml").exists() and (self.root / "template").is_dir():
            self._read_only_reason = "The Prism template repository cannot be opened as a connected project workspace."
            raise BoardError("template_workspace", self._read_only_reason, 409)
        # Construction is deliberately read-only. Local grant management opens
        # the journal lazily without owning the server singleton lock; the
        # transport calls start() to acquire that lock for its full lifetime.
        self.store: BoardStore | None = None
        self._proof = secrets.token_urlsafe(24)

    def start(self) -> "BoardService":
        """Acquire the one-process workspace lock for a serving lifetime."""

        if self._board_id is None:
            raise BoardError("workspace_read_only", self._read_only_reason or "The workspace is not an adopted connected workflow.", 409)
        if self.store is not None and self.store.process_locked:
            return self
        if self.store is not None:
            self.store.close()
        try:
            self.store = BoardStore(self.root, process_lock=True)
        except BoardLockError as exc:
            self.store = None
            raise BoardError("workspace_locked", str(exc), 409) from exc
        except CloudSyncPathError as exc:
            self.store = None
            raise BoardError("cloud_sync_path", CLOUD_SYNC_MESSAGE, 403) from exc
        except (OSError, ValueError) as exc:
            self.store = None
            raise BoardError("unsafe_state_path", str(exc), 409) from exc
        return self

    def close(self) -> None:
        store, self.store = self.store, None
        self._closed = True
        if store is not None:
            store.close()

    def compatibility(self) -> dict[str, Any]:
        """Report constructor-time eligibility without opening journal state."""

        return {"read_only": self._board_id is None, "reason": self._read_only_reason}

    def __enter__(self) -> "BoardService":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def create_participant(self, name: str, kind: str, writable: bool = False) -> dict[str, Any]:
        store = self._require_store()
        safe_name = self._clean_text(name, "name", max_length=120)
        if kind not in {"human", "agent"}:
            raise BoardError("invalid_participant_kind", "Participant kind must be `human` or `agent`.", 400)
        if not isinstance(writable, bool):
            raise BoardError("invalid_scope", "Participant writable scope must be a boolean.", 400)
        token = secrets.token_urlsafe(32)
        participant_id = str(uuid4())
        now = _now()
        with self._lock, store.transaction() as db:
            db.execute(
                "INSERT INTO grants(participant_id, token_hash, name, kind, writable, active, board_id, workflow_version, asset_digest, created_at, revoked_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, NULL)",
                (
                    participant_id,
                    _sha256(token.encode("utf-8")),
                    safe_name,
                    kind,
                    int(writable),
                    self._board_id,
                    self._workflow_version,
                    self._asset_digest_value,
                    now,
                ),
            )
        actor = self._actor_from_values(participant_id, safe_name, kind, writable, _sha256(token.encode("utf-8")))
        return {"schema_version": 1, "participant": actor.to_dict(), "token": token}

    def revoke_participant(self, participant_id: str) -> dict[str, Any]:
        store = self._require_store()
        with self._lock, store.transaction() as db:
            cursor = db.execute(
                "UPDATE grants SET active = 0, revoked_at = ? WHERE participant_id = ? AND active = 1",
                (_now(), participant_id),
            )
            if cursor.rowcount != 1:
                raise BoardError("participant_not_found", "No active participant grant has that ID.", 404)
        return {"schema_version": 1, "participant_id": participant_id, "revoked": True}

    def authenticate(self, token: str) -> Actor:
        store = self._require_store()
        if not isinstance(token, str) or len(token) < 32 or len(token) > 256:
            raise BoardError("unauthorized", "A valid participant token is required.", 401)
        token_hash = _sha256(token.encode("utf-8"))
        with store.read() as db:
            row = db.execute(
                "SELECT participant_id, name, kind, writable, active, board_id, workflow_version, asset_digest FROM grants WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if row is None or row[4] != 1:
            raise BoardError("unauthorized", "The participant grant is unknown or revoked.", 401)
        if row[5] != self._board_id or row[6] != self._workflow_version or row[7] != self._asset_digest_value:
            raise BoardError("grant_identity_changed", "The workspace workflow identity changed after this grant was created.", 409)
        self._assert_current_identity()
        return self._actor_from_values(row[0], row[1], row[2], bool(row[3]), token_hash)

    def discover(self, actor: Actor) -> dict[str, Any]:
        self._require_actor(actor)
        store = self._require_store()
        with store.read() as db:
            pending = db.execute(
                "SELECT o.operation_id, o.state, o.created_at, o.participant_id FROM operations o "
                "JOIN grants g ON g.participant_id = o.participant_id "
                "WHERE o.state != 'applied' AND (o.participant_id = ? OR (? = 1 AND g.kind = 'agent')) ORDER BY o.created_at",
                (actor.participant_id, int(actor.kind == "human" and actor.writable)),
            ).fetchall()
        skills = self._skill_summaries()
        return {
            "schema_version": 1,
            "mcp_contract": _MCP_CONTRACT,
            "board": {
                "board_id": self._board_id,
                "project_name": self._project_name,
                "platforms": list(self._platforms),
                "workflow_version": self._workflow_version,
                "mode": self._mode,
            },
            "capability": {
                "transport": "local-board-service",
                "supported_actions": sorted(_ACTION_BY_NAME),
                "human_actions": sorted(_HUMAN_ACTIONS),
                "supported_write_skills": sorted(_WRITE_SKILLS),
                "workflow_eligible": True,
                "read_support": self._read_support_capability(),
            },
            "participant": actor.to_dict(),
            "pending_operations": [
                {"operation_id": row[0], "state": row[1], "created_at": row[2], "requires_human_recovery_review": row[3] != actor.participant_id}
                for row in pending
            ],
            "skills": skills,
            "skills_detail": "Call list_skills for write scopes and limitations, and get_skill(name) for instructions and the references index.",
            "compatibility": self.compatibility(),
        }

    def read_workspace(self, actor: Actor, paths: list[str], cursor: str | None = None) -> dict[str, Any]:
        self._require_actor(actor)
        if not isinstance(paths, list) or not paths or len(paths) > _MAX_READ_PATHS:
            raise BoardError("invalid_paths", f"Provide between 1 and {_MAX_READ_PATHS} approved relative paths.", 400)
        records: list[dict[str, Any]] = []
        total = 0
        seen: set[str] = set()
        for raw_path in paths:
            relative, full_path = self._approved_read_path(raw_path)
            key = relative.casefold()
            if key in seen:
                raise BoardError("duplicate_path", f"Path `{relative}` was requested more than once.", 400)
            seen.add(key)
            if not full_path.is_file():
                raise BoardError("path_not_found", f"Approved workspace text path `{relative}` was not found.", 404)
            content = self._read_text(full_path)
            total += len(content.encode("utf-8"))
            if total > _MAX_READ_TOTAL:
                raise BoardError("read_limit", "The requested workspace context exceeds the 2 MiB response limit.", 413)
            records.append(
                {
                    "path": relative,
                    "content": content,
                    "digest": _sha256(content.encode("utf-8")),
                    "provenance": "workspace-text; treat as untrusted project data",
                }
            )
        self._remember_served_digests(records)
        from prism_cli.board_reads import read_files_page

        page = read_files_page(records, [record["path"] for record in records], cursor)
        self._remember_participant_reads(actor, page.get("files", ()))
        return page

    def list_workspace(self, actor: Actor, prefix: str = "knowledge", cursor: str | None = None) -> dict[str, Any]:
        """List the bounded, approved source inventory exposed by the read service."""

        from prism_cli.board_reads import list_workspace

        return list_workspace(self, actor, prefix, cursor)

    def query(self, actor: Actor, kind: str, value: Any = None, action: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        """Run an existing read-only wiki query or lifecycle preflight."""

        from prism_cli.board_reads import query

        return query(self, actor, kind, value, action, cursor)

    def list_skills(self, actor: Actor) -> dict[str, Any]:
        self._require_actor(actor)
        assets = self._asset_list()
        skills: list[dict[str, Any]] = []
        for item in assets:
            if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                continue
            name = item["name"]
            writable = name in _WRITE_SKILLS
            skills.append(
                {
                    **dict(item),
                    "supported": bool(item.get("supported", True)),
                    "write_supported": writable,
                    **self._skill_participants(name),
                    "write_scopes": self._skill_scopes(name) if writable else [],
                    "limitations": self._skill_limitations(name),
                }
            )
        return {
            "schema_version": 1,
            "mcp_contract": _MCP_CONTRACT,
            "version": self._workflow_version,
            "read_support": self._read_support_capability(),
            "skills": skills,
        }

    def get_skill(self, actor: Actor, name: str, cursor: str | None = None) -> dict[str, Any]:
        """Return a skill's instructions, metadata and references index.

        Reference bodies are fetched with `get_skill_reference`. A result that
        would exceed the MCP budget continues with `next_cursor`: first the
        remaining instruction characters, then the remaining required reads.
        """

        from prism_cli.board_reads import decode_cursor, encode_cursor, fit_units, reference_title, text_digest

        self._require_actor(actor)
        catalog = self._asset_get(name)
        if not isinstance(catalog, Mapping) or not isinstance(catalog.get("instructions"), str):
            raise BoardError("skill_not_found", f"Canonical skill `{name}` is unavailable for this workflow version.", 404)
        instructions = catalog["instructions"]
        digest = text_digest(instructions)
        required_reads = sorted(self._required_skill_revision_paths(name, {}, {}, []))
        reads_digest = text_digest("\n".join(required_reads))
        offset = 0
        if cursor is not None:
            position = decode_cursor(cursor, "skill", {"n", "d", "w"})
            if position["n"] != name or position["d"] != digest:
                raise BoardError("invalid_cursor", "The cursor belongs to a different skill.", 400)
            if position["w"] != reads_digest:
                raise BoardError("stale_cursor", "Workspace reads changed since the first page; request the skill again from the first page.", 409)
            offset = position["o"]
        references = []
        for reference in catalog.get("references", []):
            if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("content"), str):
                raise BoardError("workflow_assets_invalid", "Canonical workflow skill has an invalid reference.", 503)
            references.append(
                {
                    "path": reference["path"],
                    "title": reference_title(reference["path"], reference["content"]),
                    "size_chars": len(reference["content"]),
                    "digest": text_digest(reference["content"]),
                }
            )
        metadata = {
            key: value
            for key, value in dict(catalog).items()
            if key not in {"instructions", "references"}
        }
        skill = {
            **metadata,
            "write_supported": name in _WRITE_SKILLS,
            **self._skill_participants(name),
            "write_scopes": self._skill_scopes(name) if name in _WRITE_SKILLS else [],
            "limitations": self._skill_limitations(name),
            "read_support": self._read_support_capability(),
            "references": references,
            "references_note": "Fetch each reference body with get_skill_reference(name, path) and follow every next_cursor.",
        }

        # The paged sequence is the instruction characters followed by the
        # required reads; every page repeats the metadata and references index.
        text_total = len(instructions)

        def build(end: int) -> dict[str, Any]:
            following = None
            if end < text_total + len(required_reads):
                following = encode_cursor({"t": "skill", "n": name, "d": digest, "w": reads_digest, "o": end})
            text_start = min(offset, text_total)
            reads_start = max(offset - text_total, 0)
            return {
                "schema_version": 1,
                "skill": {
                    **skill,
                    "instructions": instructions[text_start:min(end, text_total)],
                    "instructions_chunk": {"offset": text_start, "total_chars": text_total, "digest": digest},
                    "required_workspace_reads": required_reads[reads_start:max(end - text_total, 0)],
                    "required_workspace_reads_chunk": {"offset": reads_start, "total": len(required_reads)},
                },
                "next_cursor": following,
            }

        return fit_units(text_total + len(required_reads), offset, build)

    def get_skill_reference(self, actor: Actor, name: str, path: str, cursor: str | None = None) -> dict[str, Any]:
        """Return one chunk of a packaged reference that belongs to the skill."""

        from prism_cli.board_reads import chunk_text, decode_cursor, encode_cursor, text_digest

        self._require_actor(actor)
        catalog = self._asset_get(name)
        if not isinstance(path, str):
            raise BoardError("invalid_path", "The reference path must be a string.", 400)
        text = None
        for reference in catalog.get("references", []):
            if isinstance(reference, Mapping) and reference.get("path") == path and isinstance(reference.get("content"), str):
                text = reference["content"]
                break
        if text is None:
            raise BoardError("reference_not_found", f"Skill `{name}` has no reference at that path; use the paths from get_skill.", 404)
        digest = text_digest(text)
        offset = 0
        if cursor is not None:
            position = decode_cursor(cursor, "reference", {"n", "p", "d"})
            if position["n"] != name or position["p"] != path or position["d"] != digest:
                raise BoardError("invalid_cursor", "The cursor belongs to a different reference.", 400)
            offset = position["o"]

        def build(content: str, end: int) -> dict[str, Any]:
            following = None
            if end < len(text):
                following = encode_cursor({"t": "reference", "n": name, "p": path, "d": digest, "o": end})
            return {
                "schema_version": 1,
                "name": name,
                "path": path,
                "content": content,
                "offset": offset,
                "total_chars": len(text),
                "digest": digest,
                "next_cursor": following,
                "provenance": "packaged canonical workflow reference; pinned to this workspace's workflow version",
            }

        return chunk_text(text, offset, build)

    @within_wiki_read_scope
    def preview_transition(
        self,
        actor: Actor,
        feature_id: str,
        action: str,
        inputs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_running()
        self._require_actor(actor, write=True, kind="human")
        self.validate_graph_inputs()
        if action not in _HUMAN_ACTIONS:
            raise BoardError("human_action_unavailable", "Direct human completion is limited to po-handoff, design-start, and dev-start.", 403)
        supplied = dict(inputs or {})
        allowed = {"semantic_review_acknowledged", "skip_advisory_review", "advisory_skip_reason", "verified_revalidation"}
        if set(supplied) - allowed:
            raise BoardError("invalid_inputs", "The transition contains unsupported input fields.", 400)
        feature = self._resolve_feature(feature_id)
        advisory_override = None
        advisory_state = feature["frontmatter"].get("advisory-review")
        if supplied.get("skip_advisory_review") is True:
            if action != "po-handoff" or advisory_state != "pending":
                raise BoardError("invalid_advisory_skip", "An advisory skip proposal is allowed only for a pending PO handoff review.", 400)
            reason = supplied.get("advisory_skip_reason")
            if not isinstance(reason, str) or not reason.strip():
                raise BoardError("advisory_skip_reason_required", "A proposed advisory skip requires a nonblank reason.", 400)
            advisory_override = ("skipped", reason.strip())
        elif "advisory_skip_reason" in supplied:
            raise BoardError("invalid_advisory_skip", "A skip reason is accepted only with `skip_advisory_review: true`.", 400)

        clear_domains = supplied.get("verified_revalidation", [])
        if not isinstance(clear_domains, list) or any(item not in {"specification"} for item in clear_domains):
            raise BoardError("invalid_revalidation", "Only PO-verified specification revalidation can be proposed by this action.", 400)
        if clear_domains and action != "po-handoff":
            raise BoardError("invalid_revalidation", "Only po-handoff can propose specification revalidation clearance.", 400)

        from prism_cli.wiki_transitions import build_board_transition_preflight

        frontmatter_overrides: dict[str, Any] = {}
        if clear_domains:
            active = feature["frontmatter"].get("revalidation", [])
            if not isinstance(active, list):
                raise BoardError("invalid_revalidation", "The feature revalidation field is malformed.", 409)
            frontmatter_overrides["revalidation"] = [item for item in active if item not in clear_domains]

        transition = build_board_transition_preflight(
            self.root,
            feature_id,
            action,
            advisory_override=advisory_override,
            frontmatter_overrides=frontmatter_overrides,
        )
        from prism_cli.board_reads import relativize_paths

        transition = relativize_paths(transition, [self.root])
        checks = list(transition.get("checks", []))
        semantic_ack = supplied.get("semantic_review_acknowledged") is True
        checks.append(
            {
                "code": "semantic-review-confirmation",
                "status": "pass" if semantic_ack else "review",
                "message": "The participant confirms a semantic review of the current source and proposed change." if semantic_ack else "Explicit semantic-review acknowledgement is required before this human action can be applied.",
            }
        )
        classification = _classification(checks)
        preview_id = str(uuid4())
        writes: list[dict[str, Any]] = []
        if isinstance(transition.get("target_status"), str) and isinstance(transition.get("target_owner"), str):
            after_feature = dict(feature["frontmatter"])
            after_feature["status"] = transition.get("target_status")
            after_feature["owner"] = transition.get("target_owner")
            after_feature["last-updated"] = date.today().isoformat()
            after_feature.update(frontmatter_overrides)
            if advisory_override is not None:
                after_feature["advisory-review"] = "skipped"
                after_feature["advisory-skip-reason"] = advisory_override[1]
            feature_after = self._replace_frontmatter(feature["content"], after_feature)
            writes = self._feature_write_set(
                feature["path"],
                feature["content"],
                feature_after,
                actor,
                preview_id,
                action,
                merge_index=True,
                merge_log=True,
            )
        source_paths = self._feature_context_paths(feature["path"], feature["frontmatter"])
        source_map = self._fingerprint_paths(source_paths)
        applicable = classification == "ready" and transition.get("action") == action and transition.get("supported") is True
        payload = {
            "preview_id": preview_id,
            "kind": "transition",
            "skill": None,
            "action": action,
            "feature_id": feature_id,
            "participant_id": actor.participant_id,
            "source_revision": _revision(source_map),
            "source_map": source_map,
            "classification": classification,
            "applicable": applicable,
            "checks": checks,
            "blockers": [item for item in checks if item.get("status") in {"blocked", "unknown", "review"}],
            "source": {"status": feature["frontmatter"].get("status"), "owner": feature["frontmatter"].get("owner")},
            "target": {"status": transition.get("target_status"), "owner": transition.get("target_owner")},
            "writes": writes,
            "moves": [],
            "created_at": _now(),
            "inputs": supplied,
        }
        self._save_preview(payload)
        return self._preview_envelope(payload)

    def get_preview(self, actor: Actor, preview_id: str) -> dict[str, Any]:
        """Return a stored preview as it was first returned, for the participant that created it."""

        self._require_actor(actor)
        preview_id = _safe_id(preview_id, "preview_id")
        store = self._require_store()
        with store.read() as db:
            row = db.execute("SELECT participant_id, payload_json FROM previews WHERE preview_id = ?", (preview_id,)).fetchone()
        if row is None or row[0] != actor.participant_id:
            raise BoardError("preview_not_found", "No preview with that ID is available to this participant.", 404)
        return self._preview_envelope(_loads(row[1]))

    def preview_skill(
        self,
        actor: Actor,
        skill: str,
        changes: list[dict[str, Any]],
        moves: list[dict[str, Any]] | None = None,
        read_revisions: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        self._require_running()
        self._require_actor(actor, write=True, kind="agent")
        if skill not in _WRITE_SKILLS:
            raise BoardError("skill_write_unavailable", f"Connected writes are not supported for skill `{skill}`.", 403)
        return self._preview_skill_proposal(actor, skill, changes, moves or [], read_revisions or {})

    def operation(self, actor: Actor, operation_id: str) -> dict[str, Any]:
        self._require_actor(actor)
        operation_id = _safe_id(operation_id, "operation_id")
        store = self._require_store()
        with store.read() as db:
            row = db.execute(
                "SELECT participant_id, state, receipt_json, created_at, updated_at, intent_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        intent = _loads(row[5]) if row is not None else {}
        if row is None or not self._can_inspect_operation(actor, row[0], intent):
            raise BoardError("operation_not_found", "No operation with that ID is available to this participant.", 404)
        receipt = _loads(row[2]) if row[2] else None
        result = {
            "schema_version": 1,
            "operation_id": operation_id,
            "state": row[1],
            "receipt": receipt,
            "created_at": row[3],
            "updated_at": row[4],
        }
        if row[1] != "applied":
            result["actor"] = intent.get("actor")
            result["remaining_changes"] = self._operation_file_states(intent)
            result["moves"] = intent.get("moves", [])
            result["recovery_review_revision"] = self._recovery_review_revision(actor, operation_id, intent, result["remaining_changes"])
        return result

    @staticmethod
    def _can_inspect_operation(actor: Actor, participant_id: str, intent: Mapping[str, Any]) -> bool:
        return participant_id == actor.participant_id or (
            actor.kind == "human" and actor.writable and intent.get("actor", {}).get("kind") == "agent"
        )

    def _recovery_review_revision(self, actor: Actor, operation_id: str, intent: Mapping[str, Any], states: list[dict[str, Any]] | None = None) -> str:
        """Bind recovery confirmation to this reviewer and the inspected inputs."""
        moves = []
        for move in intent.get("moves", []):
            current = {}
            for endpoint in ("source", "destination"):
                path = self._safe_path(move[endpoint], allow_missing=True)
                current[endpoint] = self._tree_digest(path) if path.is_dir() else ("not-directory" if path.exists() else None)
            moves.append(current)
        relevant_paths = set(intent.get("source_map", {})) - {"knowledge/wiki/index.md", "knowledge/wiki/log.md"}
        states = states if states is not None else self._operation_file_states(intent)
        managed = {write["path"] for write in intent.get("writes", []) if write.get("role") in {"index", "log"}}
        # Their target-row/entry states are relevant, while unrelated rows and
        # history appended during the review remain independently mergeable.
        reviewed_states = [{key: value for key, value in state.items() if key != "current_digest" or state["path"] not in managed} for state in states]
        return _sha256(_json({
            "operation_id": operation_id,
            "reviewer": actor.participant_id,
            "intent": intent,
            "file_states": reviewed_states,
            "move_states": moves,
            "relevant_sources": self._fingerprint_paths(relevant_paths),
        }).encode("utf-8"))

    @within_wiki_read_scope
    def recover(
        self,
        actor: Actor,
        operation_id: str,
        review_revision: str | None = None,
        semantic_review_acknowledged: bool = False,
    ) -> dict[str, Any]:
        self._require_running()
        operation_id = _safe_id(operation_id, "operation_id")
        store = self._require_store()
        with self._lock:
            self._require_actor(actor, write=True)
            with store.read() as db:
                row = db.execute(
                    "SELECT participant_id, state, intent_json, receipt_json FROM operations WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
            intent = _loads(row[2]) if row is not None else {}
            if row is None or not self._can_inspect_operation(actor, row[0], intent):
                raise BoardError("operation_not_found", "No operation with that ID is available to this participant.", 404)
            if row[1] == "applied":
                return _loads(row[3])
            cross_participant = row[0] != actor.participant_id
            if cross_participant or review_revision is not None:
                if semantic_review_acknowledged is not True or not isinstance(review_revision, str):
                    raise BoardError("recovery_review_required", "Inspect and explicitly acknowledge the remaining changes before recovering this operation.", 409)
                if review_revision != self._recovery_review_revision(actor, operation_id, intent):
                    raise BoardError("stale_recovery_review", "The operation or its relevant files changed after inspection; inspect and confirm the remaining changes again.", 409)
            if cross_participant:
                recovery_attempt = {"actor": actor.to_dict(), "review_revision": review_revision, "started_at": _now()}
                intent = {**intent, "recovery_attempts": [*intent.get("recovery_attempts", []), recovery_attempt]}
                with store.transaction() as db:
                    self._require_actor(actor, write=True)
                    db.execute("UPDATE operations SET intent_json = ?, updated_at = ? WHERE operation_id = ?", (_json(intent), recovery_attempt["started_at"], operation_id))
                    db.execute(
                        "INSERT INTO events(operation_id, participant_id, event_json, created_at) VALUES (?, ?, ?, ?)",
                        (operation_id, actor.participant_id, _json({"type": "operation-recovery-started", "actor": actor.to_dict(), "operation_id": operation_id}), recovery_attempt["started_at"]),
                    )
            return self._roll_forward(actor, operation_id, intent)

    @within_wiki_read_scope
    def apply(self, actor: Actor, preview_id: str, operation_id: str) -> dict[str, Any]:
        self._require_running()
        preview_id = _safe_id(preview_id, "preview_id")
        operation_id = _safe_id(operation_id, "operation_id")
        store = self._require_store()
        with self._lock:
            self._require_actor(actor, write=True)
            with store.read() as db:
                preview_row = db.execute(
                    "SELECT participant_id, payload_hash, payload_json, consumed_by FROM previews WHERE preview_id = ?",
                    (preview_id,),
                ).fetchone()
                existing = db.execute(
                    "SELECT participant_id, preview_id, payload_hash, state, receipt_json, intent_json FROM operations WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
            if preview_row is None or preview_row[0] != actor.participant_id:
                raise BoardError("preview_not_found", "No preview with that ID is available to this participant.", 404)
            payload = _loads(preview_row[2])
            payload_hash = preview_row[1]
            if existing is not None:
                if existing[0] != actor.participant_id or existing[1] != preview_id or existing[2] != payload_hash:
                    raise BoardError("operation_id_reused", "That operation ID is already bound to a different participant or payload.", 409)
                if existing[3] == "applied":
                    return _loads(existing[4])
                return self._roll_forward(actor, operation_id, _loads(existing[5]))
            if preview_row[3] is not None:
                raise BoardError("preview_already_submitted", f"This preview was already submitted as operation `{preview_row[3]}`; retrieve that receipt.", 409)
            if not payload.get("applicable"):
                raise BoardError("preview_blocked", "This preview is blocked, unknown, or missing required confirmation.", 409)
            self._assert_preview_fresh(payload)
            self._revalidate_operation(actor, payload)
            # Validation can read several files. Recheck them after it finishes
            # and before recording an intent that may be recovered after a crash.
            self._assert_preview_fresh(payload)
            intent = {**payload, "operation_id": operation_id, "actor": actor.to_dict()}
            self._assert_unresolved_writes_safe(operation_id, intent)
            now = _now()
            with store.transaction() as db:
                self._require_actor(actor, write=True)
                db.execute(
                    "INSERT INTO operations(operation_id, participant_id, preview_id, payload_hash, intent_json, receipt_json, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, 'pending', ?, ?)",
                    (operation_id, actor.participant_id, preview_id, payload_hash, _json(intent), now, now),
                )
                db.execute("UPDATE previews SET consumed_by = ? WHERE preview_id = ?", (operation_id, preview_id))
            return self._roll_forward(actor, operation_id, intent)

    def changes(self, actor: Actor, cursor: str | None = None) -> dict[str, Any]:
        self._require_actor(actor)
        self.validate_graph_inputs()
        store = self._require_store()
        try:
            after = int(cursor or "0")
        except (TypeError, ValueError):
            raise BoardError("invalid_cursor", "Change cursor must be a non-negative integer.", 400) from None
        if after < 0:
            raise BoardError("invalid_cursor", "Change cursor must be a non-negative integer.", 400)
        with store.read() as db:
            rows = db.execute(
                "SELECT cursor, operation_id, event_json, created_at FROM events WHERE cursor > ? ORDER BY cursor LIMIT 500",
                (after,),
            ).fetchall()
            latest = db.execute("SELECT COALESCE(MAX(cursor), 0) FROM events").fetchone()[0]
        revision_paths = self._all_board_revision_paths()
        revision = _revision(self._fingerprint_paths(revision_paths))
        next_cursor = rows[-1][0] if rows else after
        return {
            "schema_version": 1,
            "cursor": str(next_cursor),
            "head_cursor": str(latest),
            "board_revision": revision,
            "changes": [
                {"cursor": str(row[0]), "operation_id": row[1], "event": _loads(row[2]), "created_at": row[3]}
                for row in rows
            ],
        }

    def _load_identity(self) -> None:
        manifest_path = self.root / "prism.workspace.yml"
        self._reject_reparse(manifest_path, include_leaf=True)
        if not manifest_path.is_file():
            self._read_only_reason = "The workspace manifest is missing; connected workflow writes are unavailable."
            return
        try:
            data = yaml.safe_load(self._read_text(manifest_path)) or {}
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            self._read_only_reason = f"The workspace manifest cannot be read safely: {type(exc).__name__}."
            return
        schema_version = data.get("schema_version") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1:
            self._read_only_reason = "The workspace manifest schema is missing or unsupported; connected writes are read-only."
            return
        workflow = data.get("workflow")
        if not isinstance(workflow, dict) or workflow.get("version") != "1":
            self._read_only_reason = "This workspace has no supported workflow version; run explicit workflow adoption or upgrade first."
            return
        mode = workflow.get("mode")
        board_id = workflow.get("board_id")
        try:
            parsed_id = str(UUID(board_id))
        except (TypeError, ValueError, AttributeError):
            self._read_only_reason = "The workflow manifest has an invalid board identity."
            return
        project = data.get("project")
        if mode not in {"workflow", "generated"} or not isinstance(project, dict):
            self._read_only_reason = "The workflow manifest mode or project identity is unsupported."
            return
        project_name = project.get("name")
        platforms = project.get("platforms")
        if not isinstance(project_name, str) or not project_name.strip() or not isinstance(platforms, list) or not platforms:
            self._read_only_reason = "Project name and an explicit nonempty platform scope are required."
            return
        if any(not isinstance(item, str) or item not in _SUPPORTED_PLATFORMS for item in platforms) or len(set(platforms)) != len(platforms):
            self._read_only_reason = "The workflow platform scope contains invalid or duplicate IDs."
            return
        minimum_cli_error = _minimum_cli_version_error(data, manifest_path)
        if minimum_cli_error is not None:
            self._read_only_reason = minimum_cli_error
            return
        manifest_metadata = _manifest_identity_metadata(data, manifest_path)
        if manifest_metadata is None:
            self._read_only_reason = "The workspace manifest has malformed scope or path declarations."
            return
        try:
            from prism_cli.workflow_assets import asset_digest

            expected_digest = asset_digest(version="1")
        except (ImportError, AttributeError, OSError, ValueError):
            self._read_only_reason = "Canonical workflow asset fingerprints are unavailable; this workspace remains read-only."
            return
        manifest_digest = workflow.get("asset_digest")
        if not isinstance(manifest_digest, str) or manifest_digest != expected_digest:
            self._read_only_reason = "The workspace workflow assets do not match the installed canonical version; run the explicit workflow upgrade."
            return
        if not (self.root / "knowledge" / "wiki" / "SCHEMA.md").is_file() or not (self.root / "knowledge" / "wiki" / "index.md").is_file():
            self._read_only_reason = "The workspace is missing the canonical wiki schema or index."
            return
        self._board_id = parsed_id
        self._workflow_version = "1"
        self._mode = mode
        self._project_name = project_name.strip()
        self._platforms = list(platforms)
        self._asset_digest_value = expected_digest
        self._identity_facts = (
            parsed_id,
            "1",
            mode,
            expected_digest,
            self._project_name,
            tuple(self._platforms),
            schema_version,
            manifest_metadata,
        )

    def _assert_current_identity(self) -> None:
        current = BoardServiceIdentity(self.root)
        if current != self._identity_facts:
            raise BoardError("workspace_identity_changed", "The adopted workflow identity changed; writes are disabled until grants are reissued.", 409)

    def _require_store(self) -> BoardStore:
        if self._closed:
            raise BoardError("service_closed", "The board service has been closed.", 503)
        if self._board_id is None:
            reason = self._read_only_reason or "The workspace is not an adopted connected workflow."
            raise BoardError("workspace_read_only", reason, 409)
        if self.store is None:
            try:
                self.store = BoardStore(self.root, process_lock=False)
            except CloudSyncPathError as exc:
                raise BoardError("cloud_sync_path", CLOUD_SYNC_MESSAGE, 403) from exc
            except (OSError, ValueError) as exc:
                raise BoardError("unsafe_state_path", "Board state could not be opened safely.", 409) from exc
        return self.store

    def _require_running(self) -> None:
        store = self._require_store()
        if not store.process_locked:
            raise BoardError("service_not_started", "Connected writes require the server-owned workspace lock; call start() first.", 503)

    def validate_graph_inputs(self) -> None:
        """Reject reparse points throughout wiki/intake before graph reads.

        The chain from the drive root down to the workspace root is checked once
        per call, then every entry below it is classified from a single listing
        of its directory instead of re-checking all of its ancestors.
        """

        from prism_cli.workspace import COPIER_ANSWERS_FILE, PLATFORM_DIRS
        from prism_cli.wiki_transitions import _capability_paths

        files = [
            self.root / "prism.workspace.yml",
            self.root / COPIER_ANSWERS_FILE,
            *(self.root / directory for directory in PLATFORM_DIRS.values()),
            *(self.root / relative for relative in _capability_paths()),
        ]
        self._reject_reparse(self.root, include_leaf=True)
        checked: set[Path] = set()
        for path in files:
            self._reject_reparse_below(self.root, path, checked)
        # ``knowledge`` holds the wiki and every intake queue, so one walk covers all graph input trees.
        tree = self.root / "knowledge"
        self._reject_reparse_below(self.root, tree, checked)
        if tree.is_dir():
            for _child, _info in self._walk_tree(tree, reject=True):
                pass

    def _actor_from_values(self, participant_id: str, name: str, kind: str, writable: bool, token_hash: str) -> Actor:
        scopes = ("read", "write") if writable else ("read",)
        return Actor(participant_id, kind, name, writable, str(self._board_id), str(self._workflow_version), scopes, token_hash, self._proof)

    def _require_actor(self, actor: Actor, *, write: bool = False, kind: str | None = None) -> None:
        store = self._require_store()
        if not isinstance(actor, Actor) or actor._service_proof != self._proof:
            raise BoardError("unauthorized", "A server-authenticated participant is required.", 401)
        with store.read() as db:
            row = db.execute(
                "SELECT token_hash, name, kind, writable, active, board_id, workflow_version, asset_digest FROM grants WHERE participant_id = ?",
                (actor.participant_id,),
            ).fetchone()
        if row is None or row[4] != 1 or row[0] != actor._token_hash:
            raise BoardError("unauthorized", "The participant grant is unknown or revoked.", 401)
        if row[1] != actor.name or row[2] != actor.kind or bool(row[3]) != actor.writable:
            raise BoardError("actor_mismatch", "Participant identity does not match the current grant.", 401)
        if row[5] != self._board_id or row[6] != self._workflow_version or row[7] != self._asset_digest_value:
            raise BoardError("grant_identity_changed", "The workspace workflow identity changed after this grant was created.", 409)
        expected_scopes = ("read", "write") if bool(row[3]) else ("read",)
        if actor.board_id != self._board_id or actor.workflow_version != self._workflow_version or actor.scopes != expected_scopes:
            raise BoardError("actor_mismatch", "Participant scope is not bound to the current workflow identity.", 401)
        self._assert_current_identity()
        if write and not actor.writable:
            raise BoardError("write_scope_required", "This participant grant is read-only.", 403)
        if kind is not None and actor.kind != kind:
            raise BoardError("participant_kind_required", f"This operation requires a `{kind}` participant.", 403)

    def _approved_source_path(self, raw_path: Any) -> tuple[str, Path]:
        relative = self._relative_path(raw_path)
        parts = PurePosixPath(relative).parts
        if len(parts) < 3 or parts[0] != "knowledge" or parts[1] not in {"wiki", "intake"}:
            raise BoardError(
                "path_not_approved",
                f"`{_clip(relative, 120)}` cannot be read: read_workspace covers only approved paths under `knowledge/wiki/` and `knowledge/intake/`. "
                "The workspace identity (board, project and workflow version) comes from discover; `prism.workspace.yml` and `.copier-answers.yml` are not readable. "
                "Leave the path out and read the rest again.",
                403,
                {"path": _clip(relative, 120), "approved": ["knowledge/wiki/", "knowledge/intake/"]},
            )
        if parts[1] == "wiki" and (len(parts) < 3 or parts[2] not in {*_WIKI_DIRS, "SCHEMA.md", "SETTINGS.md", "index.md", "log.md", "PROJECT_FOUNDATION.md", "CONNECTED.md"}):
            raise BoardError("path_not_approved", "The requested wiki path is outside the approved source folders.", 403)
        if parts[1] == "intake" and not (len(parts) == 3 and parts[2] == "README.md") and (len(parts) < 4 or parts[2] not in {"pending", "processed", "quarantined"}):
            raise BoardError("path_not_approved", "Intake access is limited to pending, processed, and quarantined entries.", 403)
        path = self._safe_path(relative, allow_missing=True)
        return relative, path

    def _approved_read_path(self, raw_path: Any) -> tuple[str, Path]:
        relative, path = self._approved_source_path(raw_path)
        if PurePosixPath(relative).suffix.casefold() not in _TEXT_FILE_SUFFIXES:
            raise BoardError("path_not_approved", "Only approved text context files can be read.", 403)
        return relative, path

    @staticmethod
    def _read_support_capability() -> dict[str, Any]:
        return {
            "encoding": "UTF-8",
            "extensions": list(_TEXT_FILE_SUFFIXES),
            "max_file_bytes": _MAX_TEXT_FILE,
            "max_response_bytes": _MAX_READ_TOTAL,
            "max_paths_per_request": _MAX_READ_PATHS,
            "inventory_content": "metadata-only; read_workspace returns eligible file content and digests",
        }

    def _asset_list(self) -> list[Any]:
        try:
            from prism_cli.workflow_assets import list_skills
        except ImportError as exc:
            raise BoardError("workflow_assets_unavailable", "Canonical workflow assets are unavailable in this Prism installation.", 503) from exc
        result = list_skills(version=str(self._workflow_version))
        if not isinstance(result, list):
            raise BoardError("workflow_assets_invalid", "Canonical workflow skill catalog has an invalid shape.", 503)
        return result

    def _asset_get(self, name: str) -> Mapping[str, Any]:
        if not isinstance(name, str) or len(name) > 100:
            raise BoardError("invalid_skill_name", "Skill name is invalid.", 400)
        try:
            from prism_cli.workflow_assets import get_skill
        except ImportError as exc:
            raise BoardError("workflow_assets_unavailable", "Canonical workflow assets are unavailable in this Prism installation.", 503) from exc
        if not any(isinstance(item, Mapping) and item.get("name") == name for item in self._asset_list()):
            raise BoardError("skill_not_found", f"Canonical skill `{name}` is unavailable for this workflow version.", 404)
        try:
            result = get_skill(name, version=str(self._workflow_version))
        except (KeyError, FileNotFoundError) as exc:
            raise BoardError("skill_not_found", f"Canonical skill `{name}` is unavailable for this workflow version.", 404) from exc
        if not isinstance(result, Mapping):
            raise BoardError("workflow_assets_invalid", "Canonical workflow skill has an invalid shape.", 503)
        return result

    def _remember_served_digests(self, records: Iterable[Mapping[str, Any]]) -> None:
        with self._served_lock:
            for record in records:
                digests = self._served_digests.setdefault(record["path"].casefold(), [])
                if record["digest"] not in digests:
                    digests.append(record["digest"])
                    del digests[:-8]
            while len(self._served_digests) > 4096:
                self._served_digests.pop(next(iter(self._served_digests)))

    def _remember_participant_reads(self, actor: Actor, files: Iterable[Mapping[str, Any]]) -> None:
        """Record the digest of every file this participant has now received in full.

        A file returned in chunks counts only once its last chunk has been
        returned. The record is per participant and is never read for another one.
        """

        complete = [
            item for item in files
            if int(item.get("offset", 0)) + len(item["content"]) >= int(item.get("total_chars", len(item["content"])))
        ]
        if not complete:
            return
        with self._served_lock:
            reads = self._participant_reads.setdefault(actor.participant_id, {})
            for item in complete:
                key = item["path"].casefold()
                reads.pop(key, None)
                reads[key] = (item["path"], item["digest"])
            while len(reads) > 4096:
                reads.pop(next(iter(reads)))
            while len(self._participant_reads) > 256:
                self._participant_reads.pop(next(iter(self._participant_reads)))

    def _participant_read_digests(self, actor: Actor) -> dict[str, str]:
        """The digests this participant last read, by casefolded path."""

        with self._served_lock:
            return {key: digest for key, (_path, digest) in self._participant_reads.get(actor.participant_id, {}).items()}

    def _read_revision_error(self, relative: str, supplied: Any, actual: str | None) -> BoardError:
        """Tell a stale read from a digest that is simply wrong.

        A digest this service returned for the path earlier, which no longer
        matches, means the file changed after the read. Any other digest was
        mistyped or copied from somewhere else.
        """

        with self._served_lock:
            served = list(self._served_digests.get(relative.casefold(), ()))
        details = {"path": relative, "supplied": _clip(supplied, 100) if isinstance(supplied, str) else None, "expected": actual}
        shown = _clip(supplied, 100) if isinstance(supplied, str) else "null"
        if actual is None:
            return BoardError(
                "stale_read_revision",
                f"Read source `{relative}` no longer exists, so the digest {shown} cannot match. Read the workspace again.",
                409,
                details,
            )
        if supplied is None:
            return BoardError(
                "stale_read_revision",
                f"Read source `{relative}` was reported as absent but now exists with digest {actual}. Read it with read_workspace and review it.",
                409,
                details,
            )
        if supplied in served:
            return BoardError(
                "stale_read_revision",
                f"Read source `{relative}` changed after you read it: its digest was {shown} and is now {actual}. Read it again with read_workspace and review the change.",
                409,
                details,
            )
        return BoardError(
            "read_digest_mismatch",
            f"The digest supplied for `{relative}` ({shown}) is not one this board returned for that file, so it is wrong; the file's current digest is {actual}. "
            "Copy the digest from read_workspace exactly. If the file was edited after you read it, read it again.",
            409,
            details,
        )

    def _skill_summaries(self) -> list[dict[str, str]]:
        return [
            {"name": item["name"], "description": item.get("description", "")}
            for item in self._asset_list()
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        ]

    @staticmethod
    def _skill_participants(name: str) -> dict[str, Any]:
        """Which participant kinds may write with a skill, and through which tool."""

        if name not in _WRITE_SKILLS:
            return {"participant_kinds": [], "write_tools": {}}
        tools: dict[str, list[str]] = {"preview_skill": ["agent"]}
        if name in _HUMAN_ACTIONS:
            tools["preview_transition"] = ["human"]
        return {"participant_kinds": sorted({kind for kinds in tools.values() for kind in kinds}), "write_tools": tools}

    @staticmethod
    def _skill_scopes(name: str) -> list[str]:
        if name == "po-intake":
            return [
                "knowledge/wiki/features/**/*.md",
                "knowledge/wiki/personas/**/*.md",
                "knowledge/wiki/business-rules/**/*.md",
                "knowledge/intake/processed/**/MANIFEST.md",
                "knowledge/intake/quarantined/**/CONFLICT.md",
            ]
        if name == "design-intake":
            return [
                "knowledge/wiki/features/**/*.md",
                "knowledge/wiki/design/**/*.md",
                "knowledge/intake/processed/**/MANIFEST.md",
                "knowledge/intake/quarantined/**/CONFLICT.md",
            ]
        if name in {"po-clarify", "ask"}:
            return ["knowledge/wiki/features/**/*.md"]
        if name == "design-clarify":
            return ["knowledge/wiki/features/**/*.md", "knowledge/wiki/design/**/*.md"]
        if name == "dev-clarify":
            return ["knowledge/wiki/features/**/*.md", "knowledge/wiki/platform-requirements/**/*.md"]
        if name in {"po-specify", "po-handoff", "design-start", "dev-start"}:
            return ["knowledge/wiki/features/**/*.md"]
        if name in {"design-handoff", "dev-done", "feature-reopen"}:
            return [
                "knowledge/wiki/features/**/*.md",
                "knowledge/wiki/platform-requirements/**/*.md",
                "knowledge/wiki/api-contracts/**/*.md",
            ]
        return []

    @staticmethod
    def _skill_limitations(name: str) -> list[str]:
        limitations: list[str] = []
        if name in _INTAKE_SKILLS:
            limitations.append(
                "Connected intake is text-only: every required source must be UTF-8 .md, .txt, .yaml, or .yml and at most 512 KiB. "
                "Unsupported attachments and oversized files appear as metadata only and block processing; they cannot be omitted."
            )
            limitations.append(
                "The knowledge/intake/pending/ tree is a read-only move source. A proposal may move one pending folder to processed or quarantined; "
                "only the destination MANIFEST.md or CONFLICT.md may be supplied."
            )
        if name == "po-intake":
            limitations.append(
                "New features are created as `raw` + `po`. po-specify then completes the page and moves it to `specified`."
            )
        if name in {"po-clarify", "design-clarify", "dev-clarify"}:
            limitations.append(
                "Every changed requirement or design section must include the full text of at least one answer "
                "resolved by this proposal (case and whitespace differences are ignored). Paraphrases alone do not pass. "
                "This is a structural traceability check; the agent and reviewer must still verify that every edit follows the answer."
            )
        if name == "dev-clarify":
            limitations.append(
                "Resolves only dev-owned open questions, on a feature that is not `done`. It may change the feature's Open questions, "
                "Acceptance criteria, Platform scope and API surface sections and the What to build, Technical constraints, "
                "API contract reference and Acceptance criteria sections of that feature's existing platform requirement pages."
            )
        if name == "design-handoff":
            limitations.append(
                "When the feature's `## API surface` declares API work and no API contract exists yet, the proposal must create "
                "`knowledge/wiki/api-contracts/F-XXX.md` as a new page with `status: agreed`; the human confirming the preview is the agreement. "
                "Its endpoints (`METHOD /path`) and data models must trace to the API surface section. Without declared API work no contract may be "
                "proposed, and an existing contract is never rewritten. A missing, misplaced or untraceable page is rejected with "
                "`api_contract_required`, `api_contract_not_applicable`, `api_contract_exists`, `api_contract_initial_status` or "
                "`api_contract_untraceable` and `details`."
            )
        if name == "dev-done":
            limitations.append(
                "The proposed feature page must carry the delivery evidence: one substantive Implementation, Tests and Release row per "
                "declared platform in its `## Delivery evidence` table, taken from what the developer reports. A missing or invalid table is rejected "
                "with `delivery_evidence_required` or `delivery_evidence_invalid` and `details`."
            )
        if name in _HUMAN_ACTIONS:
            limitations.append(
                "Direct human action: `preview_transition` accepts only a human participant and fails with `participant_kind_required` for an agent, "
                "so an agent must not call it. The human completes the action in the board; an agent that prepares it uses `preview_skill` "
                "and the human's confirmation in the host."
            )
        if name in _WRITE_SKILLS:
            limitations.append(
                "knowledge/wiki/index.md and knowledge/wiki/log.md are service-managed outputs; do not include them in proposal changes."
            )
            return limitations
        if name in {"board-review", "setup-project"}:
            return ["Guidance is available; connected writes are unavailable until an operation-specific validator is implemented."]
        if name.startswith(("android-", "ios-", "spring-", "swiftui-", "web-")):
            return ["Application-specific writes are outside the provider-neutral workflow service."]
        return ["This skill is read-only through the connected board service."]

    def _resolve_feature(self, feature_id: str) -> dict[str, Any]:
        self.validate_graph_inputs()
        if not isinstance(feature_id, str) or not re.fullmatch(r"F-\d+", feature_id.strip(), flags=re.IGNORECASE):
            raise BoardError("invalid_feature_id", "Feature ID must use the canonical F-number form.", 400)
        from prism_cli.wiki_model import read_feature_pages, normalize_feature_id

        matches = [item for item in read_feature_pages(self.root / "knowledge" / "wiki") if normalize_feature_id(item.feature_id) == normalize_feature_id(feature_id)]
        if len(matches) != 1:
            raise BoardError("feature_not_found" if not matches else "duplicate_feature_id", "Feature ID must resolve to exactly one canonical feature page.", 404 if not matches else 409)
        path = matches[0].page.path
        relative = path.relative_to(self.root).as_posix()
        content = self._read_text(path)
        parsed = _parse_markdown(content, relative)
        return {"path": relative, "content": content, "frontmatter": parsed[0], "body": parsed[1], "feature": matches[0]}

    def _feature_context_paths(self, feature_path: str, frontmatter: Mapping[str, Any]) -> set[str]:
        paths = {"prism.workspace.yml", "knowledge/wiki/SCHEMA.md", "knowledge/wiki/SETTINGS.md", feature_path}
        from prism_cli.wiki_model import extract_markdown_links, resolve_relative_markdown_link

        feature_full = self._safe_path(feature_path)
        wiki_root = self.root / "knowledge" / "wiki"
        body = _parse_markdown(self._read_text(feature_full), feature_path)[1]
        sources = frontmatter.get("sources", [])
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, str):
                    continue
                try:
                    relative = self._relative_path(source)
                    parts = PurePosixPath(relative).parts
                    if parts[:2] == ("knowledge", "intake") and self._safe_path(relative, allow_missing=True).exists():
                        paths.add(relative)
                except BoardError:
                    continue
        for target in extract_markdown_links(body):
            resolved = resolve_relative_markdown_link(feature_full, target, wiki_root)
            if resolved is not None and resolved.is_file():
                paths.add(resolved.relative_to(self.root).as_posix())
        feature_id = frontmatter.get("id")
        if isinstance(feature_id, str):
            for directory in ("design", "platform-requirements", "api-contracts", "advisory"):
                for path in (wiki_root / directory).glob("*.md"):
                    rel = path.relative_to(self.root).as_posix()
                    linked_feature_id = _page_feature_id(self._read_text(path), path.stem)
                    if isinstance(linked_feature_id, str) and linked_feature_id.casefold() == feature_id.casefold():
                        paths.add(rel)
        return paths

    def _fingerprint_paths(self, paths: Iterable[str]) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for raw in sorted(set(paths)):
            relative = self._relative_path(raw)
            path = self._safe_path(relative, allow_missing=True)
            if not path.exists():
                result[relative] = None
                continue
            if path.is_dir():
                result[relative] = self._tree_digest(path)
            else:
                result[relative] = _sha256(path.read_bytes())
        return result

    def _save_preview(self, payload: dict[str, Any]) -> None:
        store = self._require_store()
        encoded = _json(payload)
        payload_hash = _sha256(encoded.encode("utf-8"))
        with self._lock, store.transaction() as db:
            db.execute(
                "INSERT INTO previews VALUES (?, ?, ?, ?, ?, NULL)",
                (payload["preview_id"], payload["participant_id"], payload_hash, encoded, payload["created_at"]),
            )
        payload["_payload_hash"] = payload_hash

    @staticmethod
    def _preview_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            **{key: value for key, value in payload.items() if not key.startswith("_")},
        }

    def _replace_frontmatter(self, content: str, frontmatter: Mapping[str, Any]) -> str:
        parsed = _FRONTMATTER.match(content)
        if not parsed:
            raise BoardError("invalid_feature_page", "The feature page has no valid YAML frontmatter.", 409)
        bom = "\ufeff" if content.startswith("\ufeff") else ""
        newline = "\r\n" if "\r\n" in content else "\n"
        serialized = yaml.safe_dump(dict(frontmatter), sort_keys=False, allow_unicode=True).rstrip("\r\n").replace("\n", newline)
        return bom + "---" + newline + serialized + newline + "---" + newline + parsed.group(2)

    def _feature_write_set(
        self,
        feature_path: str,
        before_feature: str,
        after_feature: str,
        actor: Actor,
        preview_id: str,
        operation: str,
        *,
        merge_index: bool,
        merge_log: bool,
        additional: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        feature_before = _file_digest(before_feature)
        writes: list[dict[str, Any]] = [
            self._write_record(feature_path, before_feature, after_feature, role="canonical")
        ]
        if additional:
            writes.extend(additional)
        affected = [_parse_markdown(after_feature, feature_path)[0]]
        feature_id = str(affected[0].get("id", ""))
        expected = {feature_id: self._index_existing_row(feature_id)}
        after_row = _index_row(affected[0])
        index_path = "knowledge/wiki/index.md"
        index_before = self._read_text(self._safe_path(index_path))
        index_after = _render_index(index_before, expected, {feature_id: after_row})
        if merge_index and index_after != index_before:
            writes.append(self._write_record(index_path, index_before, index_after, role="index", merge={"kind": "index", "expected_rows": expected, "after_rows": {feature_id: after_row}}))
        log_path = "knowledge/wiki/log.md"
        log_before = self._optional_text(self._safe_path(log_path, allow_missing=True))
        log_entry = _actor_log_entry(actor, operation, feature_id, preview_id)
        log_after = _append_once(log_before or "", f"<!-- prism:board-history:v1 preview={preview_id} -->", log_entry)
        if merge_log and log_after != (log_before or ""):
            writes.append(self._write_record(log_path, log_before, log_after, role="log", merge={"kind": "log", "marker": f"preview={preview_id}", "entry": log_entry}))
        return writes

    def _write_record(
        self,
        relative: str,
        before: str | None,
        after: str,
        *,
        role: str,
        merge: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "path": self._relative_path(relative),
            "role": role,
            "before": before,
            "before_digest": _file_digest(before),
            "after": after,
            "after_digest": _file_digest(after),
            "merge": merge,
        }

    def _index_existing_row(self, feature_id: str) -> dict[str, str] | None:
        index_path = self.root / "knowledge" / "wiki" / "index.md"
        content = self._read_text(index_path)
        matches = [match for line in content.splitlines() if (match := _INDEX_ROW.match(line)) and match.group(1).lower() == feature_id.lower()]
        if len(matches) > 1:
            raise BoardError("duplicate_index_row", f"Feature `{feature_id}` has duplicate rows in index.md.", 409)
        if not matches:
            return None
        return _index_row_from_match(matches[0])

    def _optional_text(self, path: Path) -> str | None:
        return self._read_text(path) if path.exists() else None

    def _read_text(self, path: Path) -> str:
        self._reject_reparse(path, include_leaf=True)
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_TEXT_FILE:
                raise BoardError("text_file_limit", f"Text file `{path.name}` is not a regular file or exceeds 512 KiB.", 413)
            with path.open("rb") as stream:
                data = stream.read(_MAX_TEXT_FILE + 1)
            if len(data) > _MAX_TEXT_FILE:
                raise BoardError("text_file_limit", f"Text file `{path.name}` exceeds 512 KiB.", 413)
            return data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise BoardError("unreadable_text", f"Text file `{path.name}` cannot be read as UTF-8.", 409) from exc

    def _safe_path(self, relative: str, *, allow_missing: bool = False) -> Path:
        relative = self._relative_path(relative)
        candidate = self.root.joinpath(*PurePosixPath(relative).parts)
        self._reject_reparse(candidate, include_leaf=True)
        try:
            resolved = candidate.resolve(strict=not allow_missing)
            resolved.relative_to(self.root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise BoardError("path_escape", f"Workspace path `{relative}` is not confined to this board.", 403) from exc
        return candidate

    @staticmethod
    def _relative_path(value: Any) -> str:
        if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
            raise BoardError("invalid_path", "Workspace paths must be nonempty relative POSIX paths.", 400)
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise BoardError("invalid_path", "Workspace paths must stay inside the board root.", 403)
        for part in path.parts:
            reason = BoardService._unportable_reason(part)
            if reason is not None:
                shown = re.sub(r"[\x00-\x1f\x7f]", lambda found: f"\\x{ord(found.group()):02x}", part)
                raise BoardError(
                    "invalid_path",
                    f"Workspace path segment `{_clip(shown, 80)}` {reason}, so it cannot be written on every operating system. "
                    "Rename it with letters, digits, spaces inside the name, dots, dashes and underscores only.",
                    400,
                    {"path": _clip(value, 160), "segment": _clip(shown, 80), "reason": reason},
                )
        return path.as_posix()

    @staticmethod
    def _unportable_reason(segment: str) -> str | None:
        """Why Windows refuses this path segment, or None when every system accepts it."""

        found = _WINDOWS_INVALID_CHARACTERS.search(segment)
        if found is not None:
            character = found.group()
            return "contains a control character" if ord(character) < 32 or ord(character) == 127 else f"contains `{character}`"
        if segment.endswith((".", " ")):
            return "ends in a dot or a space"
        if segment.split(".", 1)[0].upper() in _WINDOWS_DEVICE_NAMES:
            return "is a reserved device name"
        return None

    @staticmethod
    def _reject_reparse(path: Path, *, include_leaf: bool) -> None:
        parts = list(path.parents)[::-1]
        parts.append(path)
        if not include_leaf:
            parts.pop()
        for component in parts:
            BoardService._reject_reparse_component(component)

    @staticmethod
    def _reject_reparse_component(component: Path) -> None:
        try:
            info = component.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise BoardError("path_unavailable", "A workspace path cannot be inspected safely.", 403) from exc
        BoardService._reject_reparse_info(info)

    @staticmethod
    def _reject_reparse_info(info: os.stat_result) -> None:
        if reparse_kind(info) == "cloud":
            raise BoardError("cloud_sync_path", CLOUD_SYNC_MESSAGE, 403)
        if stat.S_ISLNK(info.st_mode) or _reparse_point(info):
            raise BoardError("reparse_path", "Symlinks and reparse points are not allowed in BoardService paths.", 403)

    @staticmethod
    def _reject_reparse_below(base: Path, path: Path, checked: set[Path] | None = None) -> None:
        """Check each component of ``path`` below ``base``; the chain down to ``base`` is verified by the caller."""

        current = base
        for part in path.relative_to(base).parts:
            current = current / part
            if checked is not None:
                if current in checked:
                    continue
                checked.add(current)
            BoardService._reject_reparse_component(current)

    @staticmethod
    def _walk_tree(base: Path, *, reject: bool) -> Iterator[tuple[Path, os.stat_result | None]]:
        """Yield every entry below ``base`` with its ``lstat`` information from one listing per directory.

        ``base`` and its ancestors must already be verified. Links are never
        followed: a reparse point is yielded, or rejected when ``reject`` is set,
        but never entered. An entry that vanished before it could be classified
        is yielded with ``None``. Each directory is checked again right before
        it is listed. With ``reject`` unset, a directory that cannot be listed is
        skipped, as ``Path.rglob`` skips it.
        """

        pending = [base]
        while pending:
            current = pending.pop()
            BoardService._reject_reparse_component(current)
            try:
                with os.scandir(current) as listing:
                    entries = list(listing)
            except OSError as exc:
                if not reject:
                    continue
                raise BoardError("graph_path_unavailable", "Graph input tree cannot be traversed safely.", 409) from exc
            for entry in entries:
                try:
                    info: os.stat_result | None = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    info = None
                except OSError as exc:
                    raise BoardError("path_unavailable", "A workspace path cannot be inspected safely.", 403) from exc
                child = Path(entry.path)
                if info is not None:
                    if reject:
                        BoardService._reject_reparse_info(info)
                    if stat.S_ISDIR(info.st_mode) and reparse_kind(info) == "none" and not stat.S_ISLNK(info.st_mode):
                        pending.append(child)
                yield child, info

    def _checked_tree_entries(self, path: Path) -> Iterator[tuple[str, Path, os.stat_result | None]]:
        """Yield every entry below ``path`` sorted by relative path, rejecting each reparse point as it is reached."""

        self._reject_reparse(path, include_leaf=True)
        entries = [(child.relative_to(path).as_posix(), child, info) for child, info in self._walk_tree(path, reject=False)]
        entries.sort(key=lambda item: item[0])
        for name, child, info in entries:
            if info is not None:
                self._reject_reparse_info(info)
            yield name, child, info

    def _tree_digest(self, path: Path) -> str:
        entries: list[tuple[str, str]] = []
        for name, child, info in self._checked_tree_entries(path):
            if info is not None and stat.S_ISREG(info.st_mode):
                entries.append((name, _sha256(child.read_bytes())))
            elif info is not None and stat.S_ISDIR(info.st_mode):
                entries.append((name + "/", "directory"))
            else:
                raise BoardError("unsupported_path_type", "Intake trees may contain only regular files and directories.", 409)
        return _revision({name: digest for name, digest in entries})

    def _tree_snapshot(self, path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, child, info in self._checked_tree_entries(path):
            if info is not None and stat.S_ISREG(info.st_mode):
                result[name] = _sha256(child.read_bytes())
            elif info is None or not stat.S_ISDIR(info.st_mode):
                raise BoardError("unsupported_path_type", "Intake trees may contain only regular files and directories.", 409)
        return result

    def _tree_directories(self, path: Path) -> list[str]:
        """Return every directory below an intake tree, including empty ones."""
        result: list[str] = []
        for name, _child, info in self._checked_tree_entries(path):
            if info is not None and stat.S_ISDIR(info.st_mode):
                result.append(name)
            elif info is None or not stat.S_ISREG(info.st_mode):
                raise BoardError("unsupported_path_type", "Intake trees may contain only regular files and directories.", 409)
        return result

    def _intake_before_text(self, relative: str, moves: list[dict[str, Any]]) -> str | None:
        for move in moves:
            prefix = str(move["destination"]) + "/"
            if not relative.startswith(prefix):
                continue
            suffix = relative[len(prefix):]
            source = self._safe_path(str(move["source"]) + "/" + suffix, allow_missing=True)
            if source.is_file():
                return self._read_text(source)
        return None

    def _all_board_revision_paths(self) -> set[str]:
        paths = {"prism.workspace.yml", "knowledge/wiki/index.md", "knowledge/wiki/log.md"}
        wiki = self.root / "knowledge" / "wiki"
        for path in wiki.rglob("*.md"):
            if not path.name.startswith("_"):
                paths.add(path.relative_to(self.root).as_posix())
        for queue in ("pending", "processed", "quarantined"):
            directory = self.root / "knowledge" / "intake" / queue
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file():
                        paths.add(path.relative_to(self.root).as_posix())
        return paths

    @staticmethod
    def _clean_text(value: Any, field_name: str, *, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > max_length or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
            raise BoardError("invalid_text", f"`{field_name}` must be nonblank UTF-8 text of at most {max_length} characters.", 400)
        return value.strip()

    def _preview_skill_proposal(
        self,
        actor: Actor,
        skill: str,
        changes: list[dict[str, Any]],
        moves: list[dict[str, Any]],
        read_revisions: Mapping[str, str],
    ) -> dict[str, Any]:
        self.validate_graph_inputs()
        if not isinstance(changes, list):
            raise BoardError(
                "invalid_changes",
                f"`changes` must be a list of {{`path`, `content`}} objects, not a {type(changes).__name__}.",
                400,
                {"expected": ["path", "content"], "received": type(changes).__name__},
            )
        if len(changes) > _MAX_PREVIEW_CHANGES:
            raise BoardError(
                "invalid_changes",
                f"Skill proposals must contain at most {_MAX_PREVIEW_CHANGES} text-file changes; `changes` has {len(changes)}. Drop `changes[{_MAX_PREVIEW_CHANGES}]` and every later item.",
                400,
                {"index": _MAX_PREVIEW_CHANGES, "maximum": _MAX_PREVIEW_CHANGES, "received": len(changes)},
            )
        if not isinstance(moves, list):
            raise BoardError(
                "invalid_moves",
                f"`moves` must be a list of {{`source`, `destination`}} objects, not a {type(moves).__name__}.",
                400,
                {"expected": ["source", "destination"], "received": type(moves).__name__},
            )
        if len(moves) > 1:
            raise BoardError(
                "invalid_moves",
                f"A skill proposal may contain at most one approved intake-folder move; `moves` has {len(moves)}. Drop `moves[1]` and every later item.",
                400,
                {"index": 1, "maximum": 1, "received": len(moves)},
            )
        if not isinstance(read_revisions, Mapping):
            raise BoardError("invalid_read_revisions", "Read revisions must be a path-to-digest mapping.", 400)
        supplied: dict[str, str] = {}
        for index, item in enumerate(changes):
            if not isinstance(item, Mapping) or set(item) - {"path", "content"} or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
                problem, details = _shape_details(index, item, ("path", "content"), string_fields=("path", "content"))
                raise BoardError(
                    "invalid_change",
                    f"`changes[{index}]` {problem}. Each change must contain only a relative `path` string and a UTF-8 `content` string.",
                    400,
                    details,
                )
            relative = self._relative_path(item["path"])
            if relative in supplied:
                raise BoardError("duplicate_change", f"Path `{relative}` appears more than once in this proposal.", 400)
            if len(item["content"].encode("utf-8")) > _MAX_TEXT_FILE:
                raise BoardError("text_file_limit", f"Proposed file `{relative}` exceeds 512 KiB.", 413)
            if relative in {"knowledge/wiki/index.md", "knowledge/wiki/log.md"}:
                raise BoardError("managed_file", "index.md and log.md are generated and merged by BoardService.", 403)
            self._assert_skill_write_path(skill, relative)
            supplied[relative] = item["content"]
        if not supplied:
            raise BoardError("empty_proposal", "A skill proposal must contain at least one file change.", 400)

        normalized_moves: list[dict[str, Any]] = []
        for index, item in enumerate(moves):
            if not isinstance(item, Mapping) or set(item) != {"source", "destination"}:
                problem, details = _shape_details(index, item, ("source", "destination"), string_fields=())
                raise BoardError(
                    "invalid_move",
                    f"`moves[{index}]` {problem}. Each move must contain exactly `source` and `destination`.",
                    400,
                    details,
                )
            source = self._relative_path(item["source"])
            destination = self._relative_path(item["destination"])
            self._assert_intake_move(skill, source, destination)
            source_path = self._safe_path(source)
            destination_path = self._safe_path(destination, allow_missing=True)
            if not source_path.is_dir() or destination_path.exists():
                raise BoardError("invalid_move_state", "The pending intake folder must exist and the destination must be absent.", 409)
            if skill in _INTAKE_SKILLS:
                self._validate_intake_source_tree(source_path)
            normalized_moves.append(
                {
                    "source": source,
                    "destination": destination,
                    "source_digest": self._tree_digest(source_path),
                    "source_files": self._tree_snapshot(source_path),
                    "source_directories": self._tree_directories(source_path),
                }
            )

        normalized_revisions: dict[str, str | None] = {}
        for raw_path, expected_digest in read_revisions.items():
            relative, path = self._approved_read_path(raw_path)
            if expected_digest is not None and not isinstance(expected_digest, str):
                raise BoardError("invalid_read_revision", f"Read revision for `{relative}` must be a digest or null.", 400)
            if relative.casefold() in {item.casefold() for item in normalized_revisions}:
                raise BoardError("duplicate_read_revision", f"Path `{relative}` has more than one supplied revision.", 400)
            actual = _sha256(path.read_bytes()) if path.is_file() else None
            if expected_digest != actual:
                raise self._read_revision_error(relative, expected_digest, actual)
            normalized_revisions[relative] = expected_digest

        before: dict[str, str | None] = {}
        for relative in supplied:
            path = self._safe_path(relative, allow_missing=True)
            before[relative] = self._optional_text(path)
            if before[relative] is None:
                before[relative] = self._intake_before_text(relative, normalized_moves)
        feature_changes = [path for path in supplied if path.startswith("knowledge/wiki/features/")]
        before_frontmatter: dict[str, dict[str, Any] | None] = {}
        after_frontmatter: dict[str, dict[str, Any]] = {}
        for relative in feature_changes:
            before_text = before[relative]
            before_frontmatter[relative] = _parse_markdown(before_text, relative)[0] if before_text is not None else None
            after_frontmatter[relative] = self._validate_feature_output(relative, supplied[relative], skill)

        normalized_revisions.update(
            self._assert_required_skill_revisions(
                skill, supplied, before, normalized_moves, normalized_revisions, defaults=self._participant_read_digests(actor)
            )
        )

        operation = self._validate_skill_semantics(
            actor,
            skill,
            supplied,
            before,
            before_frontmatter,
            after_frontmatter,
            normalized_moves,
        )

        preview_id = str(uuid4())
        writes = [
            self._write_record(relative, before[relative], content, role="canonical")
            for relative, content in sorted(supplied.items())
        ]
        index_keys: dict[str, dict[str, str] | None] = {}
        index_after_rows: dict[str, dict[str, str]] = {}
        for relative in feature_changes:
            after_fm = after_frontmatter[relative]
            feature_id = str(after_fm.get("id", ""))
            before_fm = before_frontmatter[relative]
            if before_fm is None or any(before_fm.get(key) != after_fm.get(key) for key in ("status", "owner", "advisory-review")):
                index_keys[feature_id] = self._index_existing_row(feature_id)
                index_after_rows[feature_id] = _index_row(after_fm)
        if index_keys:
            index_path = "knowledge/wiki/index.md"
            index_before = self._read_text(self._safe_path(index_path))
            index_after = _render_index(index_before, index_keys, index_after_rows)
            writes.append(self._write_record(index_path, index_before, index_after, role="index", merge={"kind": "index", "expected_rows": index_keys, "after_rows": index_after_rows}))

        log_subject = ", ".join(sorted(str(after_frontmatter[p].get("id")) for p in feature_changes)) or _move_subject(normalized_moves) or skill
        log_before = self._optional_text(self._safe_path("knowledge/wiki/log.md", allow_missing=True))
        log_entry = _actor_log_entry(actor, skill, log_subject, preview_id)
        log_after = _append_once(log_before or "", f"<!-- prism:board-history:v1 preview={preview_id} -->", log_entry)
        writes.append(self._write_record("knowledge/wiki/log.md", log_before, log_after, role="log", merge={"kind": "log", "marker": f"preview={preview_id}", "entry": log_entry}))

        context_paths = {"prism.workspace.yml", "knowledge/wiki/SCHEMA.md"}
        for relative, text in supplied.items():
            if relative.startswith("knowledge/wiki/features/") and before_frontmatter.get(relative):
                context_paths.update(self._feature_context_paths(relative, before_frontmatter[relative] or {}))
            if before[relative] is not None:
                context_paths.add(relative)
        for relative in normalized_revisions:
            context_paths.add(relative)
        source_map = self._fingerprint_paths(context_paths - {"knowledge/wiki/index.md", "knowledge/wiki/log.md", *supplied.keys()})
        source_revision = _revision(source_map)
        checks = operation["checks"]
        classification = operation["classification"]
        applicable = classification == "ready" and not operation.get("blockers")
        payload = {
            "preview_id": preview_id,
            "kind": "skill",
            "skill": skill,
            "action": operation.get("action"),
            "feature_id": operation.get("feature_id"),
            "participant_id": actor.participant_id,
            "source_revision": source_revision,
            "source_map": source_map,
            "classification": classification,
            "applicable": applicable,
            "checks": checks,
            "blockers": operation.get("blockers", []),
            "source": operation.get("source"),
            "target": operation.get("target"),
            "writes": writes,
            "moves": normalized_moves,
            "created_at": _now(),
            "proposed_changes": [{"path": path, "content": content} for path, content in sorted(supplied.items())],
            "read_revisions": normalized_revisions,
        }
        self._save_preview(payload)
        return self._preview_envelope(payload)

    def _assert_skill_write_path(self, skill: str, relative: str) -> None:
        if not relative.lower().endswith(".md"):
            raise BoardError("write_path_unavailable", "Connected skill writes are limited to Markdown wiki and intake text files.", 403)
        parts = PurePosixPath(relative).parts
        if parts[0] != "knowledge":
            raise BoardError("write_path_unavailable", "Connected skills can write only approved knowledge paths.", 403)
        if len(parts) >= 4 and parts[1:3] in {("intake", "processed"), ("intake", "quarantined")}:
            if skill in _INTAKE_SKILLS:
                self._safe_path(relative, allow_missing=True)
                return
        allowed: set[str]
        if skill == "po-intake":
            allowed = {"features", "personas", "business-rules"}
        elif skill == "design-intake":
            allowed = {"features", "design"}
        elif skill in {"po-clarify", "design-clarify", "dev-clarify", "ask"}:
            allowed = {"features", "design"} if skill == "design-clarify" else {"features", "platform-requirements"} if skill == "dev-clarify" else {"features"}
        elif skill == "design-handoff":
            allowed = {"features", "platform-requirements", "api-contracts"}
        elif skill == "dev-done":
            allowed = {"features", "platform-requirements", "api-contracts"}
        elif skill == "feature-reopen":
            allowed = {"features", "platform-requirements", "api-contracts"}
        else:
            allowed = {"features"}
        if len(parts) < 3 or parts[1] != "wiki" or parts[2] not in allowed:
            raise BoardError("write_path_unavailable", f"Skill `{skill}` cannot write `{relative}`.", 403)
        self._safe_path(relative, allow_missing=True)

    def _required_skill_revision_paths(
        self,
        skill: str,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        moves: list[dict[str, Any]],
    ) -> set[str]:
        required = {"knowledge/wiki/SCHEMA.md", "knowledge/wiki/index.md"}
        settings = self._safe_path("knowledge/wiki/SETTINGS.md", allow_missing=True)
        if settings.is_file():
            required.add("knowledge/wiki/SETTINGS.md")
        catalog = self._asset_get(skill)
        for reference in catalog.get("references", []):
            relative = reference.get("path") if isinstance(reference, Mapping) else None
            if not isinstance(relative, str) or not relative.startswith("knowledge/"):
                continue
            source = self._safe_path(relative, allow_missing=True)
            if source.is_file():
                required.add(relative)

        target_features: list[tuple[str, Mapping[str, Any]]] = []
        for relative, content in supplied.items():
            current = before.get(relative)
            if current is not None:
                required.add(relative)
            if relative.startswith("knowledge/wiki/features/") and current is not None:
                frontmatter = _parse_markdown(current, relative)[0]
                target_features.append((relative, frontmatter))
                required.update(self._feature_context_paths(relative, frontmatter))
            elif relative.startswith(("knowledge/wiki/design/", "knowledge/wiki/platform-requirements/", "knowledge/wiki/api-contracts/")):
                frontmatter = _parse_markdown(current or content, relative)[0]
                feature_id = frontmatter.get("feature-id")
                if isinstance(feature_id, str):
                    target = next((item for item in target_features if str(item[1].get("id", "")).casefold() == feature_id.casefold()), None)
                    if target is not None:
                        required.update(self._feature_context_paths(target[0], target[1]))

        # Intake processors need to compare against existing canonical entries,
        # not only the proposed source folder.
        if skill == "po-intake":
            for folder in ("features", "personas", "business-rules"):
                directory = self._safe_path(f"knowledge/wiki/{folder}", allow_missing=True)
                if directory.is_dir():
                    for path in directory.rglob("*.md"):
                        self._reject_reparse(path, include_leaf=True)
                        required.add(path.relative_to(self.root).as_posix())
        elif skill == "design-intake":
            directory = self._safe_path("knowledge/wiki/business-rules", allow_missing=True)
            if directory.is_dir():
                for path in directory.rglob("*.md"):
                    self._reject_reparse(path, include_leaf=True)
                    required.add(path.relative_to(self.root).as_posix())

        for move in moves:
            source = str(move["source"])
            for relative in move.get("source_files", {}):
                required.add(f"{source}/{relative}")

        # Manifest identity is reported separately by discover; it is still
        # fingerprinted into the preview, but its path is intentionally outside
        # the agent-readable workspace text surface.
        required.discard("prism.workspace.yml")
        return {
            relative for relative in required
            if relative.startswith(("knowledge/wiki/", "knowledge/intake/"))
            and self._safe_path(relative, allow_missing=True).is_file()
        }

    def _assert_required_skill_revisions(
        self,
        skill: str,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        moves: list[dict[str, Any]],
        read_revisions: Mapping[str, str | None],
        defaults: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Check the digests of the reviewed sources and return the ones filled from `defaults`.

        `defaults` maps a casefolded path to the digest the participant last
        read. It fills a required path whose revision was omitted; the filled
        digest is checked exactly like a supplied one, so a file that changed
        after that read is rejected as stale. A required path with neither a
        supplied nor a recorded digest is rejected.
        """

        required = self._required_skill_revision_paths(skill, supplied, before, moves)
        revisions_by_path = {path.casefold(): digest for path, digest in read_revisions.items()}
        filled: dict[str, str] = {}
        missing: list[str] = []
        for relative in sorted(required):
            key = relative.casefold()
            if key in revisions_by_path:
                continue
            recorded = (defaults or {}).get(key)
            if recorded is None:
                missing.append(relative)
            else:
                filled[relative] = recorded
                revisions_by_path[key] = recorded
        if missing:
            raise self._missing_read_revisions_error(missing)
        for relative in required:
            path = self._safe_path(relative)
            actual = _sha256(path.read_bytes())
            if revisions_by_path[relative.casefold()] != actual:
                raise self._read_revision_error(relative, revisions_by_path[relative.casefold()], actual)
        return filled

    @staticmethod
    def _missing_read_revisions_error(missing: list[str]) -> BoardError:
        listed: list[str] = []
        size = 0
        for relative in missing:
            if listed and size + len(relative) > 900:
                break
            listed.append(relative)
            size += len(relative) + 2
        details: dict[str, Any] = {"paths": listed, "total": len(missing), "read_with": "read_workspace"}
        while len(json.dumps(details, ensure_ascii=True, separators=(",", ":"))) > _MAX_ERROR_DETAILS_CHARS - 100 and len(listed) > 1:
            listed = listed[:-1]
            details["paths"] = listed
        rest = len(missing) - len(listed)
        return BoardError(
            "missing_read_revisions",
            "Preview requires you to have read these reviewed sources first: "
            + ", ".join(listed)
            + (f" and {rest} more" if rest else "")
            + ". Read them with read_workspace (up to 64 paths per call, following next_cursor), then preview again; "
            "the board uses the digests of the files you read, or pass them in read_revisions.",
            409,
            details,
        )

    @staticmethod
    def _assert_intake_move(skill: str, source: str, destination: str) -> None:
        if skill not in _INTAKE_SKILLS:
            raise BoardError("move_unavailable", f"Skill `{skill}` cannot move intake folders.", 403)
        src = PurePosixPath(source).parts
        dst = PurePosixPath(destination).parts
        if (
            len(src) != 4
            or src[:3] != ("knowledge", "intake", "pending")
            or len(dst) != 4
            or dst[:3] not in {("knowledge", "intake", "processed"), ("knowledge", "intake", "quarantined")}
            or src[3] != dst[3]
            or src[3] in {"", ".", ".."}
        ):
            raise BoardError("invalid_intake_move", "An intake folder may move only from pending to processed or quarantined under the same folder name.", 403)

    def _validate_intake_source_tree(self, source: Path) -> None:
        """Require every intake source to be readable text before snapshotting it.

        The first pass inspects only names and file metadata. It rejects PDFs,
        images, other extensions, oversized files, and special files before any
        source bytes are opened. UTF-8 is checked only for allowlisted files
        within the per-file limit.
        """

        candidates: list[Path] = []
        unsupported: list[str] = []
        for child in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
            self._reject_reparse(child, include_leaf=True)
            try:
                info = child.lstat()
            except OSError as exc:
                raise BoardError("intake_source_unsupported", "An intake source entry cannot be inspected safely.", 409) from exc
            if stat.S_ISDIR(info.st_mode):
                continue
            relative_name = child.relative_to(source).as_posix()
            if not stat.S_ISREG(info.st_mode):
                unsupported.append(f"{relative_name} (unsupported file type)")
            elif PurePosixPath(relative_name).suffix.casefold() not in _TEXT_FILE_SUFFIXES:
                unsupported.append(f"{relative_name} (unsupported extension)")
            elif info.st_size > _MAX_TEXT_FILE:
                unsupported.append(f"{relative_name} (over 512 KiB)")
            else:
                candidates.append(child)

        if unsupported:
            self._raise_unsupported_intake_sources(unsupported)

        unreadable: list[str] = []
        for path in candidates:
            self._reject_reparse(path, include_leaf=True)
            try:
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_TEXT_FILE:
                    unreadable.append(f"{path.relative_to(source).as_posix()} (changed or over 512 KiB)")
                    continue
                with path.open("rb") as stream:
                    data = stream.read(_MAX_TEXT_FILE + 1)
                if len(data) > _MAX_TEXT_FILE:
                    unreadable.append(f"{path.relative_to(source).as_posix()} (over 512 KiB)")
                    continue
                data.decode("utf-8")
            except (OSError, UnicodeError):
                unreadable.append(f"{path.relative_to(source).as_posix()} (not readable as UTF-8)")
        if unreadable:
            self._raise_unsupported_intake_sources(unreadable)

    @staticmethod
    def _raise_unsupported_intake_sources(paths: list[str]) -> None:
        shown = paths[:12]
        remaining = len(paths) - len(shown)
        details = ", ".join(shown)
        if remaining:
            details += f", and {remaining} more"
        raise BoardError(
            "intake_source_unsupported",
            "Text-only intake requires every source to be UTF-8 .md, .txt, .yaml, or .yml up to 512 KiB; "
            f"unreadable required source(s): {details}.",
            409,
        )

    def _validate_feature_output(self, relative: str, content: str, skill: str) -> dict[str, Any]:
        frontmatter, body = _parse_markdown(content, relative)
        self._assert_frontmatter_fields(frontmatter, {"id", "title", "status", "owner", "introduced", "last-updated", "platforms", "sources", "advisory-review", "advisory-skip-reason", "design", "design-exemption-reason", "revalidation"}, relative)
        feature_id = frontmatter.get("id")
        if not isinstance(feature_id, str) or not re.fullmatch(r"F-\d+", feature_id):
            raise BoardError("invalid_feature_output", f"Feature output `{relative}` must have a canonical F-number id.", 409)
        match = re.match(r"^(F-\d+)", PurePosixPath(relative).stem, re.IGNORECASE)
        if not match or match.group(1).lower() != feature_id.lower():
            raise BoardError("feature_path_mismatch", f"Feature output `{relative}` does not match its frontmatter id.", 409)
        if not isinstance(frontmatter.get("title"), str) or not frontmatter["title"].strip():
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` requires a nonblank title.", 409)
        status = frontmatter.get("status")
        owner = frontmatter.get("owner")
        if status not in {"raw", "specified", "ready-for-design", "in-design", "ready-for-dev", "in-dev", "done"} or owner not in {"po", "designer", "dev", "none"}:
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` has an invalid status or owner.", 409)
        if not self._valid_iso_date(frontmatter.get("introduced")) or not self._valid_iso_date(frontmatter.get("last-updated")):
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` requires ISO introduced and last-updated dates.", 409)
        sources = frontmatter.get("sources")
        if not isinstance(sources, list) or any(not isinstance(path, str) or not path.strip() or ".." in PurePosixPath(path).parts or PurePosixPath(path).is_absolute() for path in sources):
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` sources must be relative workspace paths.", 409)
        platforms = frontmatter.get("platforms")
        if not isinstance(platforms, list) or not platforms or any(not isinstance(item, str) for item in platforms) or len(set(platforms)) != len(platforms) or any(item not in self._platforms for item in platforms):
            declared = [item for item in platforms if isinstance(item, str)] if isinstance(platforms, list) else []
            outside = [item for item in declared if item not in self._platforms]
            details = {"platforms": _names(declared), "board_platforms": _names(self._platforms)}
            if outside:
                raise BoardError(
                    "invalid_feature_output",
                    f"Feature `{feature_id}` declares platform(s) {_quoted(_names(outside))} that this board does not include; "
                    f"this board's platforms are {_quoted(_names(self._platforms))}. Declare only those.",
                    409,
                    details,
                )
            raise BoardError(
                "invalid_feature_output",
                f"Feature `{feature_id}` must declare a nonempty `platforms` list of this board's platforms ({_quoted(_names(self._platforms))}), each platform once.",
                409,
                details,
            )
        if frontmatter.get("advisory-review") not in {"not-needed", "pending", "done", "skipped"}:
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` has invalid advisory-review state.", 409)
        if frontmatter.get("advisory-review") == "skipped" and not (isinstance(frontmatter.get("advisory-skip-reason"), str) and frontmatter["advisory-skip-reason"].strip()):
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` requires an advisory-skip-reason when review is skipped.", 409)
        if frontmatter.get("design") == "not-applicable" and not (isinstance(frontmatter.get("design-exemption-reason"), str) and frontmatter["design-exemption-reason"].strip()):
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` requires a design-exemption-reason when design is not applicable.", 409)
        if ("design" in frontmatter) != ("design-exemption-reason" in frontmatter):
            raise BoardError("invalid_feature_output", f"Feature `{feature_id}` must keep the design exemption fields together.", 409)
        if skill in {"po-intake", "po-specify"}:
            _require_headings(body, ("Summary", "User story", "Acceptance criteria", "Open questions", "Platform scope"), relative)
        if skill == "design-intake":
            if status not in {"specified", "ready-for-design", "in-design"}:
                raise BoardError("invalid_design_intake", "Design intake may update only a feature already routed to design.", 409)
        if skill == "po-intake" and (status, owner) != ("raw", "po"):
            raise BoardError(
                "invalid_intake_feature",
                f"PO intake creates features in `raw` + `po` status, but `{relative}` has `{status}` + `{owner}`. Set `status: raw` and `owner: po`; po-specify completes the feature and moves it to `specified`.",
                409,
                {"path": relative, "status": status, "owner": owner, "expected_status": "raw", "expected_owner": "po"},
            )
        return frontmatter

    def _validate_skill_semantics(
        self,
        actor: Actor,
        skill: str,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        before_frontmatter: Mapping[str, dict[str, Any] | None],
        after_frontmatter: Mapping[str, dict[str, Any]],
        moves: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from prism_cli.wiki_model import parse_open_question_rows, read_feature_pages

        feature_paths = list(after_frontmatter)
        checks: list[dict[str, Any]] = []
        actions: list[str] = []
        changed_features: list[dict[str, Any]] = []
        proposed_feature_ids: set[str] = set()
        for relative in feature_paths:
            old = before_frontmatter[relative]
            new = after_frontmatter[relative]
            new_id = str(new.get("id", "")).casefold()
            if new_id in proposed_feature_ids:
                raise BoardError("duplicate_feature_id", f"Feature ID `{new.get('id')}` appears more than once in this proposal.", 409)
            proposed_feature_ids.add(new_id)
            content = supplied[relative]
            if old is None:
                self._assert_feature_id_available(new["id"], except_path=None)
            else:
                self._assert_feature_id_available(new["id"], except_path=relative)
            self._validate_feature_shape(relative, content, skill)
            if old is not None:
                action = self._action_from_feature_change(skill, old, new)
                if action:
                    actions.append(action)
                elif old.get("status") != new.get("status") or old.get("owner") != new.get("owner"):
                    raise self._lifecycle_change_error(skill, relative, old, new)
                if skill in _QUESTION_SKILLS:
                    self._validate_question_change(skill, relative, before[relative] or "", content)
            changed_features.append({"path": relative, "id": new["id"], "before": old, "after": new})

        if skill == "po-intake":
            if any(item["before"] is not None for item in changed_features):
                raise BoardError("intake_existing_feature", "PO intake may create new canonical features but may not rewrite existing feature pages.", 409)
            if any(before.get(path) is not None for path in supplied if path.startswith(("knowledge/wiki/personas/", "knowledge/wiki/business-rules/"))):
                raise BoardError("intake_existing_page", "PO intake may not rewrite an existing persona or business-rule page.", 409)
        elif skill == "design-intake":
            if len(changed_features) != 1 or changed_features[0]["before"] is None:
                raise BoardError("one_existing_feature_required", "Design intake requires exactly one existing feature.", 409)
            feature = changed_features[0]
            old_text = before[feature["path"]] or ""
            old_fm, old_body = _parse_markdown(old_text, feature["path"])
            new_fm, new_body = _parse_markdown(supplied[feature["path"]], feature["path"])
            if {key: value for key, value in old_fm.items() if key != "last-updated"} != {key: value for key, value in new_fm.items() if key != "last-updated"}:
                raise BoardError("design_intake_frontmatter_scope", "Design intake preserves feature identity and lifecycle metadata.", 409)
            self._assert_only_body_sections_changed(
                old_body,
                new_body,
                {"Design", "Open questions"},
                "design_intake_feature_scope",
                "Design intake may update only the feature Design and Open questions sections.",
            )

        if skill in _INTAKE_SKILLS:
            if len(moves) != 1:
                raise BoardError("intake_move_required", f"Skill `{skill}` must move exactly one pending intake folder.", 409)
            self._validate_intake_outputs(skill, supplied, moves[0], changed_features)
        elif moves:
            raise BoardError("move_unavailable", f"Skill `{skill}` cannot move intake folders.", 403)
        self._validate_source_links(supplied, before, moves)

        for relative, content in supplied.items():
            if relative.startswith("knowledge/wiki/personas/"):
                self._validate_persona(relative, content)
            elif relative.startswith("knowledge/wiki/business-rules/"):
                self._validate_business_rule(relative, content)
            elif relative.startswith("knowledge/wiki/design/"):
                self._validate_design(relative, content)
            elif relative.startswith("knowledge/wiki/platform-requirements/"):
                self._validate_requirement(relative, content)
            elif relative.startswith("knowledge/wiki/api-contracts/"):
                self._validate_api_contract(relative, content)

        seen_named_ids: set[tuple[str, str]] = set()
        for relative, content in supplied.items():
            directory = PurePosixPath(relative).parent.as_posix()
            if directory not in {"knowledge/wiki/personas", "knowledge/wiki/business-rules"}:
                continue
            frontmatter, _body = _parse_markdown(content, relative)
            named_id = frontmatter.get("id")
            if isinstance(named_id, str):
                key = (directory, named_id.casefold())
                if key in seen_named_ids:
                    raise BoardError("duplicate_wiki_id", f"The proposal contains duplicate ID `{named_id}`.", 409)
                seen_named_ids.add(key)

        target_ids = {str(item["id"]).casefold() for item in changed_features}
        target_feature = changed_features[0] if len(changed_features) == 1 else None
        for relative, content in supplied.items():
            if relative.startswith("knowledge/wiki/design/"):
                frontmatter, _body = _parse_markdown(content, relative)
                if target_feature is None or not isinstance(frontmatter.get("feature-id"), str) or frontmatter["feature-id"].casefold() not in target_ids:
                    raise BoardError("design_feature_mismatch", f"Design page `{relative}` must link to the feature in this preview.", 409)
                if not PurePosixPath(relative).stem.casefold().startswith(str(frontmatter["feature-id"]).casefold() + "-"):
                    raise BoardError("design_path_mismatch", f"Design page `{relative}` must be named for its linked feature.", 409)
            elif relative.startswith("knowledge/wiki/platform-requirements/") or relative.startswith("knowledge/wiki/api-contracts/"):
                frontmatter, _body = _parse_markdown(content, relative)
                if target_feature is None or not isinstance(frontmatter.get("feature-id"), str) or frontmatter["feature-id"].casefold() not in target_ids:
                    raise BoardError("feature_context_mismatch", f"Page `{relative}` must belong to a feature in this preview.", 409)
                feature_id = str(target_feature["id"])
                if relative.startswith("knowledge/wiki/platform-requirements/"):
                    platform = frontmatter.get("platform")
                    declared = (target_feature["after"] or {}).get("platforms", [])
                    if platform not in declared or PurePosixPath(relative).stem.casefold() != f"{feature_id}-{platform}".casefold():
                        raise BoardError("requirement_scope_mismatch", f"Requirement `{relative}` must name one declared platform of {feature_id}.", 409)
                elif PurePosixPath(relative).stem.casefold() != feature_id.casefold():
                    raise BoardError("api_contract_path_mismatch", f"API contract `{relative}` must use its canonical {feature_id}.md path.", 409)

        if skill == "design-handoff" and target_feature is not None:
            requirement_page_list = [
                _parse_markdown(content, path)[0].get("platform")
                for path, content in supplied.items()
                if path.startswith("knowledge/wiki/platform-requirements/")
            ]
            requirement_pages = set(requirement_page_list)
            declared = set((target_feature["after"] or {}).get("platforms", []))
            if requirement_pages != declared or len(requirement_page_list) != len(declared):
                raise BoardError("requirements_incomplete", "Design handoff must propose exactly one linked requirement page for each declared platform.", 409)

        action = actions[0] if actions else None
        if len(actions) > 1:
            raise BoardError("multiple_lifecycle_actions", "One preview may perform only one lifecycle transition.", 409)

        if skill in _LIFECYCLE_SKILLS:
            expected_action = _LIFECYCLE_SKILLS[skill]
            if skill == "feature-reopen":
                if len(actions) != 1 or not actions[0].startswith("reopen-"):
                    raise BoardError("reopen_route_required", "feature-reopen must select exactly one explicit reopen route.", 409)
                expected_action = actions[0]
            elif action != expected_action:
                raise BoardError("lifecycle_action_required", f"Skill `{skill}` must propose its exact registered status and owner transition.", 409)
            if len(changed_features) != 1:
                raise BoardError("one_feature_required", f"Skill `{skill}` operates on exactly one feature per preview.", 409)
            target_feature = changed_features[0]
            old = target_feature["before"]
            if old is None:
                raise BoardError("feature_not_found", "Lifecycle skills cannot create a feature page.", 409)
            self._validate_lifecycle_write_scope(
                expected_action,
                target_feature["path"],
                before[target_feature["path"]] or "",
                supplied[target_feature["path"]],
                old,
                target_feature["after"],
            )
            self._validate_transition_source(
                expected_action,
                target_feature["path"],
                supplied[target_feature["path"]],
                old,
                target_feature["after"],
                original_content=before[target_feature["path"]] or "",
                supplied=supplied,
                before=before,
            )
            self._validate_lifecycle_related_writes(expected_action, supplied, before, target_feature)
            if expected_action == "design-handoff":
                self._require_handoff_api_contract(supplied, target_feature)
            if expected_action == "dev-done":
                self._validate_dev_done_evidence(target_feature["path"], supplied[target_feature["path"]], target_feature["after"])
            feature_id = target_feature["id"]
            transition = self._evaluate_proposed_action(expected_action, supplied, target_feature)
            checks.extend(transition.get("checks", []))
            classification = transition.get("classification", "unknown")
            if not transition.get("supported"):
                classification = "unknown" if classification == "ready" else classification
            blockers = [item for item in checks if item.get("status") in {"blocked", "unknown", "review"}]
            return {
                "action": expected_action,
                "feature_id": feature_id,
                "source": {"status": old.get("status"), "owner": old.get("owner")},
                "target": {"status": target_feature["after"].get("status"), "owner": target_feature["after"].get("owner")},
                "classification": classification,
                "checks": checks,
                "blockers": blockers,
            }

        if skill in {"ask", "po-clarify", "design-clarify", "dev-clarify"}:
            if len(changed_features) != 1:
                raise BoardError("one_feature_required", f"The `{skill}` skill requires exactly one existing feature per preview.", 409)
            if changed_features[0]["before"] is None:
                raise BoardError("feature_not_found", f"The `{skill}` skill cannot create a feature.", 409)
            self._validate_question_change(skill, changed_features[0]["path"], before[changed_features[0]["path"]] or "", supplied[changed_features[0]["path"]])
            question_rows = self._resolved_answer_rows(
                before[changed_features[0]["path"]] or "", supplied[changed_features[0]["path"]], changed_features[0]["path"]
            )
            question_answers = [answer for _number, answer in question_rows]
            old_feature_frontmatter = changed_features[0]["before"] or {}
            old_feature_body = _parse_markdown(before[changed_features[0]["path"]] or "", changed_features[0]["path"])[1]
            new_feature_body = _parse_markdown(supplied[changed_features[0]["path"]], changed_features[0]["path"])[1]
            if skill == "po-clarify":
                self._assert_only_body_sections_changed(
                    old_feature_body,
                    new_feature_body,
                    {"Open questions", "Summary", "User story", "Acceptance criteria", "Platform scope", "API surface"},
                    "clarify_scope_exceeded",
                    "PO clarify may update only the feature's Open questions, Summary, User story, Acceptance criteria, Platform scope and API surface sections.",
                )
                for section in ("Summary", "User story", "Acceptance criteria", "Platform scope", "API surface"):
                    if _section(old_feature_body, section) != _section(new_feature_body, section) and not self._answers_ground_section(
                        _section(new_feature_body, section), question_answers
                    ):
                        raise self._unlinked_answer_error("clarify_answer_unlinked", changed_features[0]["path"], [section], question_rows)
            elif skill == "design-clarify":
                self._assert_only_body_sections_changed(
                    old_feature_body,
                    new_feature_body,
                    {"Open questions"},
                    "clarify_scope_exceeded",
                    "Design clarify may update the feature's Open questions section only.",
                )
            elif skill == "dev-clarify":
                if old_feature_frontmatter.get("status") == "done":
                    raise BoardError(
                        "clarify_stage_unavailable",
                        f"Skill `dev-clarify` cannot change `{changed_features[0]['path']}` because the feature is `done`. Reopen it with feature-reopen first.",
                        409,
                        {"path": changed_features[0]["path"], "status": "done"},
                    )
                self._assert_only_body_sections_changed(
                    old_feature_body,
                    new_feature_body,
                    {"Open questions", "Acceptance criteria", "Platform scope", "API surface"},
                    "clarify_scope_exceeded",
                    "Dev clarify may update only its question table and the Acceptance criteria, Platform scope and API surface sections of the feature.",
                )
                for section in ("Acceptance criteria", "Platform scope", "API surface"):
                    if _section(old_feature_body, section) != _section(new_feature_body, section) and not self._answers_ground_section(
                        _section(new_feature_body, section), question_answers
                    ):
                        raise self._unlinked_answer_error("clarify_answer_unlinked", changed_features[0]["path"], [section], question_rows, owner="dev")
            for relative, content in supplied.items():
                if relative.startswith("knowledge/wiki/design/"):
                    old_content = before[relative]
                    if old_content is None or _page_feature_id(old_content, PurePosixPath(relative).stem) != changed_features[0]["id"]:
                        raise BoardError("design_page_unavailable", f"Skill `{skill}` may update only an existing design page linked to its feature.", 409)
                    if skill != "design-clarify":
                        raise BoardError("write_path_unavailable", f"Skill `{skill}` cannot update design pages.", 403)
                    old_fm, old_design_body = _parse_markdown(old_content, relative)
                    new_fm, new_design_body = _parse_markdown(content, relative)
                    if old_fm != new_fm:
                        changed_fields = _names(key for key in set(old_fm) | set(new_fm) if old_fm.get(key) != new_fm.get(key))
                        raise BoardError(
                            "design_frontmatter_change",
                            f"Design clarify may not change design identity or metadata; `{relative}` changes frontmatter field(s) {_quoted(changed_fields)}. Restore them to their current values.",
                            409,
                            {"path": relative, "fields": changed_fields},
                        )
                    self._assert_only_body_sections_changed(
                        old_design_body,
                        new_design_body,
                        {"Summary", "Key design decisions", "States covered", "Open design questions"},
                        "design_clarify_scope_exceeded",
                        "Design clarify may update design detail and question sections only.",
                    )
                    changed_design_sections = [
                        section for section in ("Summary", "Key design decisions", "States covered", "Open design questions")
                        if _section(old_design_body, section) != _section(new_design_body, section)
                    ]
                    ungrounded_design_sections = [
                        section for section in changed_design_sections
                        if not self._answers_ground_section(_section(new_design_body, section), question_answers)
                    ]
                    if not changed_design_sections or ungrounded_design_sections:
                        raise self._unlinked_answer_error("design_answer_unlinked", relative, ungrounded_design_sections, question_rows, owner="designer")
                elif relative.startswith("knowledge/wiki/platform-requirements/"):
                    old_content = before[relative]
                    if old_content is None or _page_feature_id(old_content, PurePosixPath(relative).stem) != changed_features[0]["id"]:
                        raise BoardError("requirement_page_unavailable", f"Skill `{skill}` may update only an existing platform requirement page linked to its feature.", 409)
                    if skill != "dev-clarify":
                        raise BoardError("write_path_unavailable", f"Skill `{skill}` cannot update platform requirement pages.", 403)
                    old_fm, old_requirement_body = _parse_markdown(old_content, relative)
                    new_fm, new_requirement_body = _parse_markdown(content, relative)
                    if old_fm != new_fm:
                        changed_fields = _names(key for key in set(old_fm) | set(new_fm) if old_fm.get(key) != new_fm.get(key))
                        raise BoardError(
                            "requirement_frontmatter_change",
                            f"Dev clarify may not change requirement identity or status; `{relative}` changes frontmatter field(s) {_quoted(changed_fields)}. Restore them to their current values.",
                            409,
                            {"path": relative, "fields": changed_fields},
                        )
                    self._assert_only_body_sections_changed(
                        old_requirement_body,
                        new_requirement_body,
                        _DEV_CLARIFY_REQUIREMENT_SECTIONS,
                        "requirement_clarify_scope_exceeded",
                        "Dev clarify may update requirement detail sections only: What to build, Technical constraints, API contract reference and Acceptance criteria.",
                    )
                    changed_requirement_sections = [
                        section for section in _DEV_CLARIFY_REQUIREMENT_ORDER
                        if _section(old_requirement_body, section) != _section(new_requirement_body, section)
                    ]
                    ungrounded_requirement_sections = [
                        section for section in changed_requirement_sections
                        if not self._answers_ground_section(_section(new_requirement_body, section), question_answers)
                    ]
                    if not changed_requirement_sections or ungrounded_requirement_sections:
                        raise self._unlinked_answer_error("requirement_answer_unlinked", relative, ungrounded_requirement_sections, question_rows, owner="dev", kind="requirement")
            design_paths = [path for path in supplied if path.startswith("knowledge/wiki/design/")]
            if skill == "design-clarify" and len(design_paths) > 1:
                raise BoardError("one_design_page_required", "Design clarify may update at most the one existing design page linked to its feature.", 409)
        checks.append({"code": "skill-structure", "status": "pass", "message": f"The `{skill}` proposal matches its connected write scope and structural validator."})
        return {
            "action": None,
            "feature_id": changed_features[0]["id"] if len(changed_features) == 1 else None,
            "source": None,
            "target": None,
            "classification": "ready",
            "checks": checks,
            "blockers": [],
        }

    @staticmethod
    def _lifecycle_change_error(skill: str, relative: str, old: Mapping[str, Any], new: Mapping[str, Any]) -> BoardError:
        spec = _ACTION_BY_NAME.get(_LIFECYCLE_SKILLS.get(skill) or "")
        if spec is not None:
            allowed = (
                f"`{skill}` moves a feature only from `{spec['source_status']}` / `{spec['source_owner']}` "
                f"to `{spec['target_status']}` / `{spec['target_owner']}`."
            )
        else:
            allowed = f"`{skill}` never changes status or owner; restore both to their current values."
        return BoardError(
            "lifecycle_action_required",
            f"`{relative}` changes status/owner from `{old.get('status')}` / `{old.get('owner')}` to `{new.get('status')}` / `{new.get('owner')}`, "
            f"which does not match a lifecycle action that `{skill}` performs. {allowed}",
            409,
            {"path": relative, "skill": skill, "from": [old.get("status"), old.get("owner")], "to": [new.get("status"), new.get("owner")]},
        )

    def _action_from_feature_change(self, skill: str, old: Mapping[str, Any], new: Mapping[str, Any]) -> str | None:
        if old.get("status") == new.get("status") and old.get("owner") == new.get("owner"):
            return None
        if skill == "feature-reopen":
            for action, target in _ACTION_BY_NAME.items():
                if action.startswith("reopen-") and (old.get("status"), old.get("owner"), new.get("status"), new.get("owner")) == (
                    "done", "none", target["target_status"], target["target_owner"]
                ):
                    return action
            return None
        action = _LIFECYCLE_SKILLS.get(skill)
        if action is None:
            return None
        target = _ACTION_BY_NAME[action]
        if (old.get("status"), old.get("owner"), new.get("status"), new.get("owner")) == (
            target["source_status"], target["source_owner"], target["target_status"], target["target_owner"]
        ):
            return action
        return None

    def _validate_transition_source(
        self,
        action: str,
        feature_path: str,
        feature_content: str,
        old: Mapping[str, Any],
        new: Mapping[str, Any],
        *,
        original_content: str,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
    ) -> None:
        spec = _ACTION_BY_NAME[action]
        if (old.get("status"), old.get("owner")) != (spec["source_status"], spec["source_owner"]):
            raise BoardError("unsupported_source_pair", f"Action `{action}` requires `{spec['source_status']}` + `{spec['source_owner']}`.", 409)
        if (new.get("status"), new.get("owner")) != (spec["target_status"], spec["target_owner"]):
            raise BoardError("invalid_transition_target", f"Action `{action}` has a fixed registered destination.", 409)
        if action == "po-specify":
            _require_headings(
                _parse_markdown(feature_content, feature_path)[1],
                ("Summary", "User story", "Acceptance criteria", "Open questions", "Platform scope", "Design", "Related features", "API surface", "Board review summary", "Post-ship notes"),
                feature_path,
                " po-specify completes a raw feature: give each of them one line of supported content or an explicit statement that nothing exists yet, "
                "for example `Not started.` under Design, `None identified.` under Related features, `None.` under API surface, "
                "`Not reviewed yet.` under Board review summary and `Not shipped yet.` under Post-ship notes. "
                "Any API surface text other than `None.` needs an API contract page before dev-start, so write `None.` unless the intake material or an answered question states an API change. "
                "Keep questions in the Open questions table, never in these sections.",
            )
            self._validate_substantive_spec(_parse_markdown(feature_content, feature_path)[1], feature_path)
        if action.startswith("reopen-"):
            domains = new.get("revalidation")
            expected = {
                "reopen-spec": ["specification", "design", "implementation", "tests", "release"],
                "reopen-design": ["design", "implementation", "tests", "release"],
                "reopen-dev": ["implementation", "tests", "release"],
            }[action]
            if domains != expected:
                raise BoardError("revalidation_required", "The reopen route must add its exact required revalidation domains.", 409)
            self._validate_reopen_record(action, original_content, feature_content, old, supplied, before, relative=feature_path)

    def _validate_lifecycle_write_scope(
        self,
        action: str,
        relative: str,
        original: str,
        proposed: str,
        old: Mapping[str, Any],
        new: Mapping[str, Any],
    ) -> None:
        old_fm, old_body = _parse_markdown(original, relative)
        new_fm, new_body = _parse_markdown(proposed, relative)
        allowed_frontmatter = {"status", "owner", "last-updated"}
        if action == "po-handoff":
            allowed_frontmatter |= {"advisory-review", "advisory-skip-reason", "revalidation"}
        elif action == "design-handoff":
            allowed_frontmatter.add("revalidation")
        elif action == "dev-done":
            allowed_frontmatter.add("revalidation")
        elif action.startswith("reopen-"):
            allowed_frontmatter.add("revalidation")
        changed = {
            key for key in set(old_fm) | set(new_fm)
            if old_fm.get(key) != new_fm.get(key)
        }
        if changed - allowed_frontmatter:
            offending = _names(changed - allowed_frontmatter)
            allowed_names = sorted(allowed_frontmatter)
            raise BoardError(
                "lifecycle_frontmatter_scope",
                f"Action `{action}` cannot change frontmatter fields: {', '.join(offending)} in `{relative}`. Restore them to their current values; this action may change only {_quoted(allowed_names)}.",
                409,
                {"path": relative, "fields": offending, "allowed": allowed_names},
            )
        timestamp = new_fm.get("last-updated")
        if timestamp is not None:
            try:
                date.fromisoformat(str(timestamp))
            except ValueError as exc:
                raise BoardError("invalid_last_updated", "Lifecycle updates require an ISO date in last-updated.", 409) from exc
        if action == "po-handoff":
            if old_fm.get("advisory-review") == new_fm.get("advisory-review"):
                if old_fm.get("advisory-skip-reason") != new_fm.get("advisory-skip-reason"):
                    raise BoardError("advisory_skip_scope", "A skip reason may change only when this handoff proposes a pending-to-skipped advisory decision.", 409)
            elif (old_fm.get("advisory-review"), new_fm.get("advisory-review")) != ("pending", "skipped"):
                raise BoardError("advisory_skip_scope", "PO handoff may propose only pending-to-skipped advisory review.", 409)
            elif not isinstance(new_fm.get("advisory-skip-reason"), str) or not new_fm["advisory-skip-reason"].strip():
                raise BoardError("advisory_skip_reason_required", "A skipped advisory review requires a nonblank reason.", 409)
        clearable = {
            "po-handoff": {"specification"},
            "design-handoff": {"design"},
            "dev-done": {"implementation", "tests", "release"},
        }.get(action, set())
        if action.startswith("reopen-"):
            expected_domains = {
                "reopen-spec": ["specification", "design", "implementation", "tests", "release"],
                "reopen-design": ["design", "implementation", "tests", "release"],
                "reopen-dev": ["implementation", "tests", "release"],
            }[action]
            if new_fm.get("revalidation") != expected_domains:
                raise BoardError("revalidation_required", "The reopen route must set exactly its registered revalidation domains.", 409)
        else:
            old_domains = old_fm.get("revalidation", [])
            new_domains = new_fm.get("revalidation", [])
            if not isinstance(old_domains, list) or not isinstance(new_domains, list) or any(not isinstance(item, str) for item in old_domains):
                raise BoardError("invalid_revalidation", "Revalidation fields must be lists of known domains.", 409)
            expected_domains = [item for item in old_domains if item not in clearable]
            if new_domains != expected_domains:
                raise BoardError("revalidation_scope", f"Action `{action}` may clear only its verified revalidation domains.", 409)

        if action in {"po-handoff", "design-start", "dev-start", "design-handoff"}:
            if old_body != new_body:
                # Names the sections and the first line that differ; the body of this action may not change at all.
                self._assert_only_body_sections_changed(
                    old_body, new_body, set(), "lifecycle_body_scope", f"Action `{action}` changes only lifecycle metadata on the feature page."
                )
                raise BoardError("lifecycle_body_scope", f"Action `{action}` changes only lifecycle metadata on the feature page.", 409)
        elif action == "dev-done":
            self._assert_only_body_sections_changed(
                old_body,
                new_body,
                {"Delivery evidence", "Post-ship notes"},
                "lifecycle_body_scope",
                "Dev done may update delivery evidence and post-ship notes only.",
            )
        elif action.startswith("reopen-"):
            self._assert_only_body_sections_changed(
                old_body,
                new_body,
                {"Delivery evidence", "Reopen history"},
                "lifecycle_body_scope",
                "Feature reopen may archive delivery evidence and append reopen history only.",
            )
        elif action == "po-specify":
            if old_fm.get("platforms") != new_fm.get("platforms") or old_fm.get("sources") != new_fm.get("sources"):
                raise BoardError("specification_identity_change", "PO specify preserves source and platform scope.", 409)

    @staticmethod
    def _validate_dev_done_evidence(relative: str, content: str, frontmatter: Mapping[str, Any]) -> None:
        """Require the proposed feature page to carry valid delivery evidence.

        The evidence arrives as part of the proposal, so one preview shows the
        evidence row beside the status change. The rules are the ones the
        transition pre-check applies to a recorded table.
        """

        from prism_cli.wiki_model import parse_delivery_evidence

        declared = [item for item in frontmatter.get("platforms", []) if isinstance(item, str)]
        _frontmatter, body = _parse_markdown(content, relative)
        rows, problems = parse_delivery_evidence(body, declared)
        if not problems:
            return
        example = "| " + " | ".join([declared[0] if declared else "backend", "<implementation reference>", "<test command and result>", "<release artifact or target>"]) + " |"
        details: dict[str, Any] = {
            "path": relative,
            "platforms": _names(declared),
            "missing_platforms": _names(set(item.casefold() for item in declared) - set(rows)),
            "problems": [_clip(item, 200) for item in problems[:6]],
        }
        if not rows:
            raise BoardError(
                "delivery_evidence_required",
                f"Dev done needs the delivery evidence in the proposal: the `## Delivery evidence` table in the proposed `{relative}` has no platform rows. "
                f"Add one row per declared platform ({_quoted(_names(declared))}) with the implementation, test and release references the developer reports, "
                f"for example `{example}`. Ask the developer for what is missing; do not invent it.",
                409,
                details,
            )
        raise BoardError(
            "delivery_evidence_invalid",
            f"The `## Delivery evidence` table in the proposed `{relative}` is not valid: {' '.join(_clip(item, 200) for item in problems[:6])} "
            "It needs exactly one row per declared platform, each with a substantive Implementation, Tests and Release cell.",
            409,
            details,
        )

    def _validate_lifecycle_related_writes(
        self,
        action: str,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        feature: Mapping[str, Any],
    ) -> None:
        related = {
            path for path in supplied
            if path.startswith(("knowledge/wiki/platform-requirements/", "knowledge/wiki/api-contracts/"))
        }
        if action in {"po-specify", "po-handoff", "design-start", "dev-start"} and related:
            raise BoardError("lifecycle_write_scope", f"Action `{action}` may change only its feature, managed index, and log.", 409)
        allowed_prefixes = {
            "design-handoff": ("knowledge/wiki/platform-requirements/", "knowledge/wiki/api-contracts/"),
            "dev-done": ("knowledge/wiki/platform-requirements/", "knowledge/wiki/api-contracts/"),
        }
        if action.startswith("reopen-"):
            allowed = ("knowledge/wiki/platform-requirements/", "knowledge/wiki/api-contracts/")
        else:
            allowed = allowed_prefixes.get(action, ())
        if related - {path for path in supplied if path.startswith(allowed)}:
            raise BoardError("lifecycle_write_scope", f"Action `{action}` cannot write those linked artifact types.", 403)
        for relative in related:
            original = before.get(relative)
            proposed = supplied[relative]
            if action in {"dev-done", "feature-reopen"} and original is None:
                raise BoardError("linked_page_not_found", f"Action `{action}` can update only existing linked artifact `{relative}`.", 409)
            new_fm, new_body = _parse_markdown(proposed, relative)
            old_fm, old_body = _parse_markdown(original, relative) if original is not None else ({}, "")
            if not isinstance(new_fm.get("feature-id"), str) or new_fm["feature-id"].casefold() != str(feature["id"]).casefold():
                raise BoardError("feature_context_mismatch", f"Linked artifact `{relative}` does not belong to {feature['id']}.", 409)
            if action == "design-handoff":
                if relative.startswith("knowledge/wiki/api-contracts/"):
                    self._validate_handoff_api_contract(relative, original, proposed, supplied, feature)
                    continue
                if original is None and new_fm.get("status") != "pending":
                    raise BoardError("requirement_initial_status", "Design handoff creates new platform requirements in pending status.", 409)
                if original is not None and (old_fm != new_fm or old_body != new_body):
                    raise BoardError("requirement_body_change", "Design handoff may not rewrite an existing platform requirement.", 409)
            elif action == "dev-done":
                status = new_fm.get("status")
                if relative.startswith("knowledge/wiki/platform-requirements/"):
                    if status not in {old_fm.get("status"), "done"}:
                        raise BoardError("requirement_status_change", "Dev done may preserve a requirement status or mark that linked requirement done.", 409)
                elif status not in {old_fm.get("status"), "implemented"}:
                    raise BoardError("api_status_change", "Dev done may preserve an API status or mark that linked contract implemented.", 409)
                if {key: val for key, val in old_fm.items() if key != "status"} != {key: val for key, val in new_fm.items() if key != "status"} or old_body != new_body:
                    raise BoardError(
                        "linked_page_scope",
                        f"Dev done may change only the `status` of an existing linked requirement or API contract, but `{relative}` also changes its text or other fields. Restore everything except `status` to the current text.",
                        409,
                        {"path": relative},
                    )
            elif action.startswith("reopen-"):
                if relative.startswith("knowledge/wiki/platform-requirements/"):
                    if new_fm.get("status") not in {"pending", "in-progress"}:
                        raise BoardError("requirement_invalidation", "Reopen may invalidate a requirement only to pending or in-progress.", 409)
                elif new_fm.get("status") not in {"draft", "agreed"}:
                    raise BoardError("api_invalidation", "Reopen may invalidate an API contract only to draft or agreed.", 409)
                if {key: val for key, val in old_fm.items() if key != "status"} != {key: val for key, val in new_fm.items() if key != "status"} or old_body != new_body:
                    raise BoardError(
                        "linked_page_scope",
                        f"Reopen may change only the `status` of an existing linked artifact, but `{relative}` also changes its text or other fields. Restore everything except `status` to the current text.",
                        409,
                        {"path": relative},
                    )

    def _validate_handoff_api_contract(
        self,
        relative: str,
        original: str | None,
        proposed: str,
        supplied: Mapping[str, str],
        feature: Mapping[str, Any],
    ) -> None:
        """Design handoff may create the feature's API contract once, as `agreed`, from the feature's API surface."""

        feature_id = str(feature["id"])
        new_fm, new_body = _parse_markdown(proposed, relative)
        if original is not None:
            old_fm, old_body = _parse_markdown(original, relative)
            if old_fm != new_fm or old_body != new_body:
                raise BoardError(
                    "api_contract_exists",
                    f"Design handoff creates an API contract only as a new page; `{relative}` already exists and may not be rewritten. Restore its current text or leave it out of the proposal.",
                    409,
                    {"path": relative, "feature_id": feature_id},
                )
            return
        surface = section_text(_parse_markdown(supplied[feature["path"]], feature["path"])[1], "API surface")
        if not api_surface_declared(surface):
            raise BoardError(
                "api_contract_not_applicable",
                f"{feature_id} declares no API work in its `## API surface` section, so design handoff may not create `{relative}`. Leave the page out of the proposal.",
                409,
                {"path": relative, "feature_id": feature_id},
            )
        if new_fm.get("status") != "agreed":
            raise BoardError(
                "api_contract_initial_status",
                f"Design handoff creates a new API contract as `agreed` (the human confirming the preview is the agreement), but `{relative}` has status `{_clip(new_fm.get('status'), 40)}`. Set `status: agreed`.",
                409,
                {"path": relative, "status": _clip(new_fm.get("status"), 40), "expected_status": "agreed"},
            )
        others = self._feature_api_contract_paths(feature, supplied) - {relative}
        if others:
            raise BoardError(
                "api_contract_exists",
                f"{feature_id} already has an API contract at {_quoted(sorted(others)[:3])}; design handoff creates no second one. Leave `{relative}` out of the proposal.",
                409,
                {"path": relative, "feature_id": feature_id, "existing": sorted(others)[:3]},
            )
        error = _api_contract_scope_error(relative, feature_id, new_body, surface)
        if error is not None:
            raise error

    def _require_handoff_api_contract(self, supplied: Mapping[str, str], feature: Mapping[str, Any]) -> None:
        """Design handoff must carry an API contract when the feature declares API work and none exists yet."""

        surface = section_text(_parse_markdown(supplied[feature["path"]], feature["path"])[1], "API surface")
        if not api_surface_declared(surface) or self._feature_api_contract_paths(feature, supplied):
            return
        feature_id = str(feature["id"])
        canonical = f"knowledge/wiki/api-contracts/{feature_id}.md"
        sections = ["Endpoints", "Data models", "Authentication requirements", "Notes"]
        raise BoardError(
            "api_contract_required",
            f"{feature_id} declares API work in its `## API surface` section but has no API contract. Add a new page `{canonical}` to the proposal with "
            f"`feature-id: {feature_id}`, `version: 1`, `status: agreed` and the sections {_quoted(sections)}, written only from that API surface "
            "(list each endpoint as `METHOD /path`). The human confirming this preview is the agreement.",
            409,
            {"path": canonical, "feature_id": feature_id, "status": "agreed", "sections": sections},
        )

    def _feature_api_contract_paths(self, feature: Mapping[str, Any], supplied: Mapping[str, str]) -> set[str]:
        """Workspace paths of the API contracts that cover a feature: its own pages, pages it links and pages in the proposal."""

        from prism_cli.wiki_transitions import api_contract_link_targets

        feature_id = str(feature["id"]).casefold()
        wiki_root = self.root / "knowledge" / "wiki"
        found = {path for path in supplied if path.startswith("knowledge/wiki/api-contracts/")}
        directory = wiki_root / "api-contracts"
        if directory.is_dir():
            for path in sorted(directory.glob("*.md")):
                linked = _page_feature_id(self._read_text(path), path.stem)
                if isinstance(linked, str) and linked.casefold() == feature_id:
                    found.add(path.relative_to(self.root).as_posix())
        sources = [path for path in supplied if path.startswith("knowledge/wiki/platform-requirements/")]
        resolved_root = self.root.resolve()
        for relative in [feature["path"], *sources]:
            body = _parse_markdown(supplied[relative], relative)[1]
            for target in api_contract_link_targets(body, self.root / relative, wiki_root):
                if target.is_file():
                    try:
                        found.add(target.relative_to(resolved_root).as_posix())
                    except ValueError:
                        continue
        return found

    def _validate_reopen_record(
        self,
        action: str,
        original: str,
        proposed: str,
        old: Mapping[str, Any],
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        relative: str | None = None,
    ) -> None:
        _old_fm, old_body = _parse_markdown(original, relative)
        _new_fm, new_body = _parse_markdown(proposed, relative)
        old_history = _section(old_body, "Reopen history")
        new_history = _section(new_body, "Reopen history")
        if not new_history.startswith(old_history):
            raise BoardError("reopen_history_not_append_only", "Reopen history must preserve all previous records and append one new record.", 409)
        addition = new_history[len(old_history):]
        expected_heading = f"reopen-{action.removeprefix('reopen-')}"
        headings = re.findall(r"(?im)^###\s+(\d{4}-\d{2}-\d{2})\s+-\s+(reopen-[a-z]+)\s*$", addition)
        if len(headings) != 1 or headings[0][1] != expected_heading:
            raise BoardError("reopen_record_required", "A reopen proposal must append exactly one dated record for its selected route.", 409)
        labels = ("Reason", "Impact review", "Affected platforms", "Affected artifacts", "Prior completion/release evidence", "Requirement/API invalidations")
        values: dict[str, str] = {}
        for label in labels:
            match = re.search(rf"(?im)^\s*-\s*{re.escape(label)}:\s*(.*?)\s*$", addition)
            value = match.group(1).strip() if match else ""
            if match and label == _ARCHIVE_LABEL:
                value = _label_block(addition, label, labels)
            if not match or not value or (label != "Affected platforms" and len(value) < 8):
                hint = ""
                if label == "Requirement/API invalidations":
                    hint = (
                        " Name each invalidated requirement or API page as `knowledge/wiki/.../page.md: done -> in-progress` (its current and new status), "
                        "or, when no page is invalidated, write a sentence such as `No requirement or API page is invalidated.`"
                    )
                raise BoardError("impact_review_required", f"Reopen history must include a `- {label}:` bullet with substantive evidence (at least 8 characters).{hint}", 409, {"label": label})
            values[label] = value
        if any(token in " ".join(values.values()).casefold() for token in ("[reason", "[impact", "[affected", "[prior completion", "todo", "tbd", "placeholder")):
            raise BoardError("impact_review_required", "Reopen history cannot contain copied placeholders or unresolved template text.", 409)
        declared = old.get("platforms")
        affected = {part.strip().strip("`[]") for part in re.split(r"[,;]", values["Affected platforms"]) if part.strip()}
        if not isinstance(declared, list) or not affected or not affected.issubset(set(declared)):
            raise BoardError("reopen_platform_scope", "Reopen history must name affected platform IDs from the feature's declared scope.", 409)
        from prism_cli.wiki_model import parse_delivery_evidence_cells

        # The same parser that dev-done applies to the evidence it accepts, so every
        # table dev-done wrote can be archived here. Rows keep their own column order.
        declared_platforms = [item for item in declared if isinstance(item, str)]
        declared_keys = {item.strip().lower() for item in declared_platforms}
        prior_canonical, prior_cells, _prior_problems = parse_delivery_evidence_cells(old_body, declared_platforms)
        if not prior_cells or set(prior_cells) != declared_keys:
            raise BoardError("delivery_evidence_missing", "Reopen must archive the existing active delivery evidence for every declared platform.", 409)
        normalized_archive = _normalized_table_text(values[_ARCHIVE_LABEL])
        for cells in prior_cells.values():
            row_text = "| " + " | ".join(cells) + " |"
            if _normalized_table_text(row_text) not in normalized_archive:
                raise BoardError(
                    "delivery_evidence_not_archived",
                    f"Reopen history must retain each prior delivery-evidence row verbatim under `- {_ARCHIVE_LABEL}:`, "
                    "on that line or on the lines directly below it, before the next `- Label:` line or heading. "
                    "A table row or a list item both work. "
                    f"Missing row: {_clip(row_text, 300)}",
                    409,
                    {"path": relative, "label": _ARCHIVE_LABEL, "missing_row": _clip(row_text, 300)},
                )
        new_delivery = _section(new_body, "Delivery evidence")
        active_canonical, active_cells, _active_problems = parse_delivery_evidence_cells(new_body, declared_platforms)
        # A row the parser does not read as a platform row still counts as active evidence.
        known_rows = list(active_cells.values())
        for cells in _table_rows(new_delivery, expected_columns=4):
            if cells not in known_rows:
                raise BoardError("delivery_evidence_still_active", "Reopen may preserve only unchanged evidence for unaffected platforms explicitly reaffirmed in the impact review.", 409)
        affected_keys = {item.lower() for item in affected}
        for platform, cells in active_cells.items():
            if platform not in prior_canonical or active_canonical[platform] != prior_canonical[platform] or platform in affected_keys:
                raise BoardError("delivery_evidence_still_active", "Reopen may preserve only unchanged evidence for unaffected platforms explicitly reaffirmed in the impact review.", 409)
            if "reaffirm" not in values["Impact review"].casefold() or re.sub(r"\s+", " ", "| " + " | ".join(cells) + " |").casefold() not in re.sub(r"\s+", " ", values["Impact review"]).casefold():
                raise BoardError("delivery_evidence_not_reaffirmed", "Unchanged evidence kept active must be named as reaffirmed in the impact review.", 409)
        related_paths = {
            path for path in supplied
            if path.startswith(("knowledge/wiki/platform-requirements/", "knowledge/wiki/api-contracts/"))
        }
        invalidations = values["Requirement/API invalidations"]
        artifacts = values["Affected artifacts"]
        listed_paths = set(re.findall(r"knowledge/wiki/(?:platform-requirements|api-contracts)/[A-Za-z0-9_.-]+\.md", invalidations))
        if listed_paths != related_paths:
            raise BoardError("reopen_invalidation_mismatch", "Reopen history must list exactly the linked requirement/API pages proposed in this write.", 409)
        for relative in related_paths:
            prior = before.get(relative)
            if prior is None:
                raise BoardError("linked_page_not_found", f"Reopen may invalidate only existing linked artifact `{relative}`.", 409)
            old_page_fm, _ = _parse_markdown(prior, relative)
            new_page_fm, _ = _parse_markdown(supplied[relative], relative)
            old_status = str(old_page_fm.get("status", ""))
            new_status = str(new_page_fm.get("status", ""))
            status_phrase = re.compile(rf"{re.escape(relative)}\s*:?\s*{re.escape(old_status)}\s*(?:->|→)\s*{re.escape(new_status)}", re.IGNORECASE)
            if old_status == new_status or not status_phrase.search(invalidations):
                raise BoardError(
                    "reopen_invalidation_mismatch",
                    f"Reopen history must record `{relative}` changing exactly from `{old_status}` to `{new_status}`. "
                    f"Write it under `- Requirement/API invalidations:` as `{relative}: {old_status} -> {new_status}` (an arrow, not a sentence).",
                    409,
                    {"path": relative, "from": old_status, "to": new_status},
                )
            if relative not in artifacts:
                raise BoardError(
                    "reopen_artifact_missing",
                    f"`- Affected artifacts:` must also name the invalidated page `{relative}` by its full relative path.",
                    409,
                    {"path": relative},
                )

    @staticmethod
    def _assert_only_body_sections_changed(
        old_body: str,
        new_body: str,
        allowed_sections: set[str],
        code: str,
        message: str,
    ) -> None:
        if _body_without_sections(old_body, allowed_sections) == _body_without_sections(new_body, allowed_sections):
            return
        allowed = {heading.strip().casefold() for heading in allowed_sections}
        headings: list[str] = []
        for body in (old_body, new_body):
            for match in re.finditer(r"(?m)^##\s+(.+?)\s*#*\s*$", body):
                name = match.group(1).strip()
                if name.casefold() not in allowed and name not in headings:
                    headings.append(name)
        changed = _names(name for name in headings if _section(old_body, name) != _section(new_body, name))
        if changed:
            blank_only = [name for name in changed if _section(old_body, name).split() == _section(new_body, name).split()]
            note = ""
            if blank_only:
                note = (
                    f" Section(s) {_quoted(blank_only)} differ only in whitespace, such as the file's final newline or its line endings: "
                    "copy every unchanged section exactly as read_workspace returned it, and end the file the way it ended."
                )
                if old_body.endswith("\n") and not new_body.endswith("\n"):
                    note += " The current file ends with a newline character; end `content` with one."
            details: dict[str, Any] = {"sections": changed}
            if blank_only:
                details["whitespace_only"] = blank_only
            first = next((name for name in changed if name not in blank_only), None)
            if first is not None:
                difference = _first_line_difference(_section(old_body, first), _section(new_body, first))
                if difference is not None:
                    note += f" First difference in `{first}`: current line `{_clip(difference[0], 100)}`, proposed line `{_clip(difference[1], 100)}`."
            raise BoardError(
                code,
                f"{message} The proposal changes section(s) {_quoted(changed)}; restore them to their current text.{note}",
                409,
                details,
            )
        # Every named section matches, so a section heading or the text between sections differs.
        difference = _first_line_difference(
            _body_without_sections(old_body, allowed_sections), _body_without_sections(new_body, allowed_sections)
        )
        if difference is not None:
            raise BoardError(
                code,
                f"{message} Outside the sections it may change, "
                + (f"the current page has the line `{_clip(difference[0], 100)}` where the proposal has `{_clip(difference[1], 100)}`" if difference[0] else f"the proposal adds the line `{_clip(difference[1], 100)}`")
                + "; restore the current text, and add or remove no section heading.",
                409,
                {"current_line": _clip(difference[0], 100), "proposed_line": _clip(difference[1], 100)},
            )
        raise BoardError(code, message, 409)

    @staticmethod
    def _resolved_answers(before: str, after: str, path: str | None = None) -> list[str]:
        return [answer for _number, answer in BoardService._resolved_answer_rows(before, after, path)]

    @staticmethod
    def _resolved_answer_rows(before: str, after: str, path: str | None = None) -> list[tuple[str, str]]:
        from prism_cli.wiki_model import parse_open_question_rows

        old_rows, _ = parse_open_question_rows(_parse_markdown(before, path)[1])
        new_rows, _ = parse_open_question_rows(_parse_markdown(after, path)[1])
        new_by_number = {row["number"]: row for row in new_rows}
        answers: list[tuple[str, str]] = []
        for row in old_rows:
            new_row = new_by_number.get(row["number"])
            if row["status"] == "open" and new_row and new_row["status"].startswith("resolved:"):
                answer = new_row["status"][len("resolved:"):].strip()
                if answer:
                    answers.append((str(row["number"]), answer))
        return answers

    @staticmethod
    def _unlinked_answer_error(
        code: str,
        path: str,
        sections: list[str],
        answers: list[tuple[str, str]],
        *,
        owner: str | None = None,
        kind: str = "design",
    ) -> BoardError:
        """Build the traceability rejection that names the section and the answers to paste."""

        numbers = [number for number, _answer in answers][:20]
        starts = {number: _clip(answer, 160) for number, answer in answers[:5]}
        where = f"`{sections[0]}` in `{path}`" if sections else f"a {kind} section of `{path}`"
        subject = f"Updated {where}" if sections else f"This proposal changes no {kind} section of `{path}`; the changed section"
        owned = f" by this proposal to {owner}-owned question(s)" if owner else " by this proposal to question(s)"
        message = (
            f"{subject} must include the full text of an answer resolved{owned} "
            f"{', '.join(numbers) or 'none'}. Paste one of those answers verbatim into the section "
            "(case and whitespace differences are ignored, but paraphrases alone do not pass)."
        )
        details: dict[str, Any] = {"path": path, "section": sections[0] if sections else None, "resolved_questions": numbers, "resolved_answers": starts}
        if len(sections) > 1:
            details["sections"] = sections[:10]
        return BoardError(code, message, 409, details)

    @staticmethod
    def _answers_ground_section(section: str, answers: list[str]) -> bool:
        normalized = re.sub(r"\s+", " ", section).casefold()
        # The answer must stand as whole words: `no` is not found inside `not` or `know`.
        def whole_words(answer: str) -> str:
            return r"(?<!\w)" + re.escape(re.sub(r"\s+", " ", answer).strip().casefold()) + r"(?!\w)"

        return bool(answers) and any(
            re.search(whole_words(answer), normalized)
            for answer in answers
            if answer.strip()
        )

    def _validate_feature_shape(self, relative: str, content: str, skill: str) -> None:
        frontmatter, body = _parse_markdown(content, relative)
        from prism_cli.wiki_model import parse_open_question_rows, REVALIDATION_DOMAINS

        questions, errors = parse_open_question_rows(body)
        if errors:
            raise BoardError("invalid_open_questions", "; ".join(errors), 409)
        for item in questions:
            if not isinstance(item.get("number"), str) or not item["number"].isdigit() or int(item["number"]) < 1 or not item.get("question") or item.get("owner") not in {"po", "designer", "dev"}:
                raise BoardError("invalid_open_question", f"Feature `{relative}` contains a malformed open question.", 409)
        revalidation = frontmatter.get("revalidation", [])
        if not isinstance(revalidation, list) or any(not isinstance(item, str) or item not in REVALIDATION_DOMAINS for item in revalidation) or len(set(revalidation)) != len(revalidation):
            raise BoardError("invalid_revalidation", f"Feature `{relative}` contains invalid revalidation domains.", 409)
        _validate_no_placeholders(body, relative)

    @staticmethod
    def _validate_substantive_spec(body: str, relative: str) -> None:
        for heading in ("Summary", "User story", "Acceptance criteria", "Platform scope"):
            if not _section(body, heading).strip():
                raise BoardError("incomplete_specification", f"Feature `{relative}` has an empty `{heading}` section.", 409)
        criteria = [line for line in _section(body, "Acceptance criteria").splitlines() if re.match(r"\s*(?:[-*+]\s+|\d+[.)]\s+)\S", line)]
        if not criteria:
            raise BoardError("incomplete_specification", f"Feature `{relative}` needs at least one acceptance criterion.", 409)

    def _validate_question_change(self, skill: str, relative: str, before: str, after: str) -> None:
        from prism_cli.wiki_model import parse_open_question_rows

        old_frontmatter, old_body = _parse_markdown(before, relative)
        new_frontmatter, new_body = _parse_markdown(after, relative)
        mutable_frontmatter = {"last-updated"}
        if {key: value for key, value in old_frontmatter.items() if key not in mutable_frontmatter} != {key: value for key, value in new_frontmatter.items() if key not in mutable_frontmatter}:
            changed_fields = _names(
                key for key in set(old_frontmatter) | set(new_frontmatter)
                if key not in mutable_frontmatter and old_frontmatter.get(key) != new_frontmatter.get(key)
            )
            raise BoardError(
                "clarify_frontmatter_change",
                f"Skill `{skill}` cannot alter feature lifecycle or identity metadata; `{relative}` changes frontmatter field(s) {_quoted(changed_fields)}. Restore them; only `last-updated` may change.",
                409,
                {"path": relative, "fields": changed_fields},
            )
        if skill == "ask" and _strip_section(old_body, "Open questions") != _strip_section(new_body, "Open questions"):
            # Names the sections that differ, and says when they differ only in whitespace such as the final newline.
            self._assert_only_body_sections_changed(
                old_body, new_body, {"Open questions"}, "ask_scope_exceeded", "The ask skill may update only the feature Open questions section."
            )
            raise BoardError("ask_scope_exceeded", "The ask skill may update only the feature Open questions section.", 409)
        old_rows, old_errors = parse_open_question_rows(old_body)
        new_rows, new_errors = parse_open_question_rows(new_body)
        if old_errors or new_errors:
            raise BoardError("invalid_open_questions", "; ".join(old_errors + new_errors), 409)
        if len({row["number"] for row in old_rows}) != len(old_rows) or len({row["number"] for row in new_rows}) != len(new_rows):
            raise BoardError("duplicate_question_number", f"Feature `{relative}` must use each open-question number once.", 409)
        new_by_number = {row["number"]: row for row in new_rows}
        allowed_owner = _QUESTION_SKILLS.get(skill)
        resolved_count = 0
        for row in old_rows:
            updated = new_by_number.get(row["number"])
            if updated is None or updated["question"] != row["question"] or updated["owner"] != row["owner"]:
                raise BoardError("question_deleted_or_changed", f"Question {row['number']} on `{relative}` must be preserved with the same text and owner.", 409)
            if row["status"] == "open" and updated["status"] != "open":
                if skill == "ask":
                    raise BoardError("ask_scope_exceeded", "The ask skill may add questions but cannot answer existing questions.", 409)
                if allowed_owner is not None and row["owner"] != allowed_owner:
                    raise BoardError("question_owner_mismatch", f"Skill `{skill}` cannot resolve {row['owner']}-owned question {row['number']}.", 409)
                if not updated["status"].startswith("resolved:") or not updated["status"][len("resolved:"):].strip():
                    raise BoardError("answer_required", f"Question {row['number']} needs a substantive resolved answer.", 409)
                resolved_count += 1
            elif updated["status"] != row["status"]:
                raise BoardError("question_status_change", f"Previously resolved question {row['number']} must be preserved unchanged.", 409)
        old_numbers = {row["number"] for row in old_rows}
        for row in new_rows:
            if row["number"] not in old_numbers and row["status"] != "open":
                raise BoardError(
                    "new_question_must_be_open",
                    f"Question {row['number']} on `{relative}` is not in the current Open questions table (its numbers are {', '.join(sorted(old_numbers, key=lambda number: (len(number), number))) or 'none'}), "
                    "so it counts as a new question, and a new question must have status `open`. "
                    "To answer an existing question, keep its number, text and owner and change only its Status to `resolved: <answer>`. "
                    "A question that is not in the table is added first with the ask skill.",
                    409,
                    {"path": relative, "question": row["number"], "existing_questions": sorted(old_numbers, key=lambda number: (len(number), number))[:30]},
                )
        added = [row for row in new_rows if row["number"] not in old_numbers]
        if skill == "ask" and (len(added) != 1 or resolved_count):
            raise BoardError("question_required", "The ask skill must add exactly one new owned open question and preserve all existing questions.", 409)
        if skill == "ask" and int(added[0]["number"]) != max([int(row["number"]) for row in old_rows if row["number"].isdigit()] or [0]) + 1:
            raise BoardError("question_number_not_next", "The ask skill must use the next sequential question number.", 409)
        if skill in {"po-clarify", "design-clarify", "dev-clarify"} and resolved_count == 0:
            raise BoardError("answer_required", f"Skill `{skill}` must resolve at least one owned open question.", 409)

    def _validate_intake_outputs(
        self,
        skill: str,
        supplied: Mapping[str, str],
        move: Mapping[str, Any],
        features: list[dict[str, Any]],
    ) -> None:
        destination = str(move["destination"])
        destination_files = {path.removeprefix(destination + "/"): content for path, content in supplied.items() if path.startswith(destination + "/")}
        quarantined = destination.startswith("knowledge/intake/quarantined/")
        if quarantined:
            report = destination_files.get("CONFLICT.md", "")
            if set(supplied) != {destination + "/CONFLICT.md"} or len(report.strip()) < 40:
                raise BoardError("quarantine_write_scope", "A conflict quarantine writes only a substantive CONFLICT.md report; no wiki files may change.", 409)
            _validate_no_placeholders(report, destination + "/CONFLICT.md")
            return
        if any(path.startswith("knowledge/intake/") and not path.startswith(destination + "/") for path in supplied):
            raise BoardError("intake_write_scope", "An intake proposal may write only its final destination manifest.", 403)
        if skill == "po-intake":
            manifest = destination_files.get("MANIFEST.md")
            if not manifest or not features:
                raise BoardError("intake_manifest_required", "Processed PO intake needs a MANIFEST.md and at least one structured feature.", 409)
            destination_paths = set(destination_files)
            if destination_paths != {"MANIFEST.md"}:
                raise BoardError("intake_manifest_scope", "PO intake may write only MANIFEST.md inside the processed intake folder.", 409)
            manifest_text = manifest.casefold()
            for relative, content in supplied.items():
                if relative.startswith(("knowledge/wiki/features/", "knowledge/wiki/personas/", "knowledge/wiki/business-rules/")):
                    frontmatter, _body = _parse_markdown(content, relative)
                    named_id = frontmatter.get("id")
                    if relative.casefold() not in manifest_text or (isinstance(named_id, str) and named_id.casefold() not in manifest_text):
                        raise BoardError("intake_manifest_incomplete", f"The processed intake manifest must list `{relative}` and its canonical ID.", 409)
        if skill == "design-intake":
            if len(features) != 1:
                raise BoardError("one_feature_required", "Design intake is scoped to one feature per preview.", 409)
            designs = [path for path in supplied if path.startswith("knowledge/wiki/design/")]
            if len(designs) != 1:
                raise BoardError("design_page_required", "Design intake must propose exactly one design page.", 409)
            if set(destination_files) - {"MANIFEST.md"}:
                raise BoardError("intake_manifest_scope", "Design intake may write only an optional MANIFEST.md inside the processed intake folder.", 409)

    def _validate_source_links(
        self,
        supplied: Mapping[str, str],
        before: Mapping[str, str | None],
        moves: list[dict[str, Any]],
    ) -> None:
        """Reject a source link that will not resolve once the proposal applies.

        Features list `sources` paths. Personas list `sources` and business rules
        list one `source`; those fields may hold free text, so only an entry that
        starts with `knowledge/` is checked. An entry already on the page before
        this proposal is left alone, so editing a page cannot be blocked by an
        older link. A new entry may not lie under `knowledge/intake/pending/`, and
        must exist on disk, be written by the proposal or lie in the processed
        folder that the proposal's own intake move creates.
        """

        for relative, content in sorted(supplied.items()):
            if relative.startswith("knowledge/wiki/features/"):
                field_name, path_only = "sources", True
            elif relative.startswith("knowledge/wiki/personas/"):
                field_name, path_only = "sources", False
            elif relative.startswith("knowledge/wiki/business-rules/"):
                field_name, path_only = "source", False
            else:
                continue
            existing = set(self._source_entries(before.get(relative), relative, field_name))
            for entry in self._source_entries(content, relative, field_name):
                if entry in existing:
                    continue
                parts = source_link_parts(entry, path_only=path_only)
                if parts is None:
                    continue
                if is_pending_intake_source(parts):
                    expected = self._processed_source_expectation(parts, moves)
                    raise BoardError(
                        "intake_source_not_processed",
                        f"`{relative}` lists source `{entry}`, which is in the pending intake queue. "
                        f"A pending folder moves when intake applies, so this link would stop resolving; list `{expected}` instead.",
                        409,
                        {"path": relative, "source": entry, "expected": expected},
                    )
                if not self._source_exists_after(parts, moves, supplied):
                    raise BoardError(
                        "source_link_missing",
                        f"`{relative}` lists source `{entry}`, which will not exist once this proposal applies. "
                        "List a workspace path that exists, such as a file in the processed intake folder this proposal moves.",
                        409,
                        {"path": relative, "source": entry},
                    )

    @staticmethod
    def _source_entries(text: str | None, relative: str, field_name: str) -> list[str]:
        if text is None:
            return []
        try:
            value = _parse_markdown(text, relative)[0].get(field_name)
        except BoardError:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]
        return []

    @staticmethod
    def _processed_source_expectation(parts: tuple[str, ...], moves: list[dict[str, Any]]) -> str:
        """The processed path that replaces a pending source path, following the proposal's own move."""

        for move in moves:
            source = tuple(PurePosixPath(str(move["source"])).parts)
            if tuple(part.casefold() for part in parts[: len(source)]) == tuple(part.casefold() for part in source):
                return "/".join((*PurePosixPath(str(move["destination"])).parts, *parts[len(source):]))
        return processed_source_path(parts)

    def _source_exists_after(self, parts: tuple[str, ...], moves: list[dict[str, Any]], supplied: Mapping[str, str]) -> bool:
        relative = "/".join(parts)
        if relative in supplied or any(path.startswith(relative + "/") for path in supplied):
            return True
        folded = tuple(part.casefold() for part in parts)
        for move in moves:
            destination = tuple(PurePosixPath(str(move["destination"])).parts)
            if folded[: len(destination)] != tuple(part.casefold() for part in destination):
                continue
            inside = "/".join(parts[len(destination):])
            if not inside:
                return True
            files = move.get("source_files", {})
            return (
                inside in files
                or inside in move.get("source_directories", [])
                or any(name.startswith(inside + "/") for name in files)
            )
        try:
            return self._safe_path(relative, allow_missing=True).exists()
        except BoardError as error:
            if error.code == "invalid_path":
                return False
            raise

    def _validate_persona(self, relative: str, content: str) -> None:
        frontmatter, body = _parse_markdown(content, relative)
        self._assert_frontmatter_fields(frontmatter, {"id", "name", "introduced", "sources"}, relative)
        if not isinstance(frontmatter.get("id"), str) or not re.fullmatch(r"P-\d+", frontmatter["id"]):
            raise BoardError("invalid_persona", f"Persona `{relative}` requires a P-number id.", 409)
        if not isinstance(frontmatter.get("name"), str) or not frontmatter["name"].strip():
            raise BoardError("invalid_persona", f"Persona `{relative}` requires a nonblank name.", 409)
        if not self._valid_iso_date(frontmatter.get("introduced")) or not isinstance(frontmatter.get("sources"), list) or not frontmatter["sources"]:
            raise BoardError("invalid_persona", f"Persona `{relative}` requires an introduced date and source list.", 409)
        self._assert_named_id_available(relative, frontmatter["id"], "id")
        _require_headings(body, ("Who they are", "Goals", "Pain points", "Features that serve this persona"), relative)
        _validate_no_placeholders(body, relative)

    def _validate_business_rule(self, relative: str, content: str) -> None:
        frontmatter, body = _parse_markdown(content, relative)
        self._assert_frontmatter_fields(frontmatter, {"id", "title", "introduced", "source"}, relative)
        if not isinstance(frontmatter.get("id"), str) or not re.fullmatch(r"BR-\d+", frontmatter["id"]):
            raise BoardError("invalid_business_rule", f"Business rule `{relative}` requires a BR-number id.", 409)
        if not isinstance(frontmatter.get("title"), str) or not frontmatter["title"].strip() or not self._valid_iso_date(frontmatter.get("introduced")) or not isinstance(frontmatter.get("source"), str) or not frontmatter["source"].strip():
            raise BoardError("invalid_business_rule", f"Business rule `{relative}` requires title, introduced date, and source.", 409)
        self._assert_named_id_available(relative, frontmatter["id"], "id")
        _require_headings(body, ("Rule", "Rationale", "Affected features", "Exceptions"), relative)
        if not PurePosixPath(relative).stem.casefold().startswith(frontmatter["id"].casefold() + "-"):
            raise BoardError("business_rule_path_mismatch", f"Business rule `{relative}` must be named for {frontmatter['id']}.", 409)
        _validate_no_placeholders(body, relative)

    def _validate_design(self, relative: str, content: str) -> None:
        frontmatter, body = _parse_markdown(content, relative)
        self._assert_frontmatter_fields(frontmatter, {"feature-id", "title", "designer", "date", "figma"}, relative)
        if not isinstance(frontmatter.get("feature-id"), str):
            raise BoardError("invalid_design", f"Design page `{relative}` must identify its feature.", 409)
        if not isinstance(frontmatter.get("title"), str) or not frontmatter["title"].strip() or not self._valid_iso_date(frontmatter.get("date")) or not isinstance(frontmatter.get("figma"), str) or not frontmatter["figma"].strip():
            raise BoardError("invalid_design", f"Design page `{relative}` requires a title, date, and Figma reference or `not applicable`.", 409)
        _require_headings(body, ("Summary", "Key design decisions", "States covered", "Component references", "Open design questions"), relative)
        _validate_no_placeholders(body, relative)

    def _validate_requirement(self, relative: str, content: str) -> None:
        frontmatter, body = _parse_markdown(content, relative)
        self._assert_frontmatter_fields(frontmatter, {"feature-id", "platform", "status"}, relative)
        if frontmatter.get("platform") not in self._platforms or frontmatter.get("status") not in {"pending", "in-progress", "done"}:
            raise BoardError("invalid_requirement", f"Platform requirement `{relative}` has an invalid platform or status.", 409)
        _require_headings(body, ("What to build", "Technical constraints", "Design reference", "API contract reference", "Acceptance criteria", "Dependencies"), relative)
        _validate_no_placeholders(body, relative)

    def _validate_api_contract(self, relative: str, content: str) -> None:
        frontmatter, body = _parse_markdown(content, relative)
        self._assert_frontmatter_fields(frontmatter, {"feature-id", "version", "status"}, relative)
        if frontmatter.get("version") != 1 or frontmatter.get("status") not in {"draft", "agreed", "implemented"}:
            raise BoardError("invalid_api_contract", f"API contract `{relative}` has an invalid status.", 409)
        _require_headings(body, ("Endpoints", "Data models", "Authentication requirements", "Notes"), relative)
        _validate_no_placeholders(body, relative)

    @staticmethod
    def _assert_frontmatter_fields(frontmatter: Mapping[str, Any], allowed: set[str], relative: str) -> None:
        unknown = set(frontmatter) - allowed
        if unknown:
            unknown_names = _names(unknown)
            raise BoardError(
                "unknown_frontmatter_fields",
                f"`{relative}` contains fields outside its canonical schema: {', '.join(unknown_names)}. Remove them; the allowed fields are {_quoted(sorted(allowed))}.",
                409,
                {"path": relative, "fields": unknown_names, "allowed": sorted(allowed)},
            )

    @staticmethod
    def _valid_iso_date(value: Any) -> bool:
        from prism_cli.wiki_model import parse_iso_date

        return parse_iso_date(value) is not None

    def _assert_feature_id_available(self, feature_id: str, *, except_path: str | None) -> None:
        from prism_cli.wiki_model import read_feature_pages, normalize_feature_id

        pages = read_feature_pages(self.root / "knowledge" / "wiki")
        matches = [page for page in pages if normalize_feature_id(page.feature_id) == normalize_feature_id(feature_id) and (except_path is None or page.page.path.relative_to(self.root).as_posix() != except_path)]
        if matches:
            raise BoardError("duplicate_feature_id", f"Feature ID `{feature_id}` already exists at another canonical path.", 409)

    def _assert_named_id_available(self, relative: str, value: str, field: str) -> None:
        from prism_cli.wiki_model import read_markdown_pages

        directory = self.root / PurePosixPath(relative).parent
        for page in read_markdown_pages(directory):
            if page.path.relative_to(self.root).as_posix() == relative:
                continue
            if isinstance(page.frontmatter.get(field), str) and page.frontmatter[field].casefold() == value.casefold():
                raise BoardError("duplicate_wiki_id", f"ID `{value}` already exists at `{page.path.relative_to(self.root).as_posix()}`.", 409)

    def _evaluate_proposed_action(self, action: str, supplied: Mapping[str, str], feature: Mapping[str, Any]) -> dict[str, Any]:
        spec = _ACTION_BY_NAME[action]
        temporary = tempfile.TemporaryDirectory(prefix="prism-board-preview-")
        self._build_candidate_root(Path(temporary.name), supplied, [])
        candidate_feature = _parse_markdown(supplied[feature["path"]], feature["path"])[0]
        candidate_feature["status"] = spec["source_status"]
        candidate_feature["owner"] = spec["source_owner"]
        candidate_content = self._replace_frontmatter(supplied[feature["path"]], candidate_feature)
        (Path(temporary.name) / feature["path"]).write_text(candidate_content, encoding="utf-8")
        try:
            from prism_cli.board_reads import relativize_paths
            from prism_cli.wiki_transitions import build_board_transition_preflight

            candidate = Path(temporary.name)
            evaluated = build_board_transition_preflight(candidate, str(feature["id"]), action)
            # The scratch tree and the workspace are never part of a result.
            return relativize_paths(evaluated, [candidate, candidate.resolve(), self.root])
        finally:
            temporary.cleanup()

    def _build_candidate_root(self, destination: Path, supplied: Mapping[str, str], moves: list[dict[str, Any]]) -> None:
        self.validate_graph_inputs()
        manifest = self._safe_path("prism.workspace.yml")
        (destination / "knowledge").mkdir(parents=True, exist_ok=True)
        self._reject_reparse(manifest, include_leaf=True)
        (destination / "prism.workspace.yml").write_bytes(manifest.read_bytes())
        source_wiki = self._safe_path("knowledge/wiki")
        self._copy_tree_safely(source_wiki, destination / "knowledge" / "wiki")
        for move in moves:
            source = self._safe_path(move["source"])
            target = destination / move["destination"]
            self._copy_tree_safely(source, target)
        for relative, content in supplied.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def _copy_tree_safely(self, source: Path, destination: Path) -> None:
        self._reject_reparse(source, include_leaf=True)
        destination.mkdir(parents=True, exist_ok=True)
        pending = [(source, destination)]
        while pending:
            current_source, current_destination = pending.pop()
            self._reject_reparse_component(current_source)
            try:
                with os.scandir(current_source) as entries:
                    children = sorted(list(entries), key=lambda entry: entry.name)
            except OSError as exc:
                raise BoardError("candidate_copy_failed", "A candidate wiki/intake tree cannot be inspected safely.", 409) from exc
            for entry in children:
                source_child = Path(entry.path)
                target_child = current_destination / entry.name
                try:
                    info: os.stat_result | None = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    info = None
                except OSError as exc:
                    raise BoardError("path_unavailable", "A workspace path cannot be inspected safely.", 403) from exc
                if info is not None:
                    self._reject_reparse_info(info)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        target_child.mkdir(parents=True, exist_ok=True)
                        pending.append((source_child, target_child))
                    elif entry.is_file(follow_symlinks=False):
                        self._reject_reparse_component(source_child)
                        target_child.parent.mkdir(parents=True, exist_ok=True)
                        target_child.write_bytes(source_child.read_bytes())
                    else:
                        raise BoardError("candidate_copy_failed", "Candidate trees may contain only regular files and directories.", 409)
                except OSError as exc:
                    raise BoardError("candidate_copy_failed", "A candidate wiki/intake tree cannot be copied safely.", 409) from exc

    def _assert_preview_fresh(self, payload: Mapping[str, Any]) -> None:
        self.validate_graph_inputs()
        if payload.get("participant_id") is None:
            raise BoardError("invalid_preview", "The stored preview has no participant binding.", 409)
        for relative, expected in payload.get("source_map", {}).items():
            path = self._safe_path(relative, allow_missing=True)
            actual = None
            if path.is_file():
                actual = _sha256(path.read_bytes())
            elif path.is_dir():
                actual = self._tree_digest(path)
            if actual != expected:
                raise BoardError("stale_preview", f"Relevant source `{relative}` changed after this preview.", 409)
        for move in payload.get("moves", []):
            source = self._safe_path(move["source"], allow_missing=True)
            destination = self._safe_path(move["destination"], allow_missing=True)
            if not source.exists() or destination.exists() or self._tree_digest(source) != move["source_digest"]:
                raise BoardError("stale_move", f"Intake move `{move['source']}` changed after this preview.", 409)
        for write in payload.get("writes", []):
            if write.get("role") in {"index", "log"}:
                continue
            path = self._safe_path(write["path"], allow_missing=True)
            actual = _sha256(path.read_bytes()) if path.is_file() else None
            if actual is None:
                moved_before = self._intake_before_text(write["path"], payload.get("moves", []))
                actual = _file_digest(moved_before)
            if actual != write.get("before_digest"):
                raise BoardError("stale_write", f"Proposed target `{write['path']}` changed after this preview.", 409)
        for write in payload.get("writes", []):
            if write.get("role") == "index":
                self._assert_index_rows(write["path"], write["merge"].get("expected_rows", {}))

    def _revalidate_operation(self, actor: Actor, payload: Mapping[str, Any]) -> None:
        """Re-evaluate current deterministic rules, including calendar checks."""
        if payload.get("kind") == "transition":
            from prism_cli.wiki_transitions import build_board_transition_preflight

            feature = self._resolve_feature(payload["feature_id"])
            expected_paths = set(payload.get("source_map", {}))
            if self._feature_context_paths(feature["path"], feature["frontmatter"]) - expected_paths:
                raise BoardError("stale_preview", "New relevant feature context appeared after this preview; review it before applying.", 409)
            inputs = payload.get("inputs", {})
            overrides = {}
            if inputs.get("verified_revalidation"):
                overrides["revalidation"] = [item for item in feature["frontmatter"].get("revalidation", []) if item not in inputs["verified_revalidation"]]
            advisory = ("skipped", inputs["advisory_skip_reason"].strip()) if inputs.get("skip_advisory_review") is True else None
            current = build_board_transition_preflight(self.root, payload["feature_id"], payload["action"], advisory_override=advisory, frontmatter_overrides=overrides)
            if current.get("classification") != "ready" or not current.get("supported"):
                raise BoardError("checks_changed", "Current workflow checks no longer permit this action. Refresh the preview; calendar freshness is re-evaluated at apply time.", 409)
            return
        supplied = {item["path"]: item["content"] for item in payload.get("proposed_changes", [])}
        before = {path: self._optional_text(self._safe_path(path, allow_missing=True)) for path in supplied}
        for path in before:
            if before[path] is None:
                before[path] = self._intake_before_text(path, payload.get("moves", []))
        revisions = dict(payload.get("read_revisions", {}))
        # Target rows and append-only history have their own merge checks. A
        # change to an unrelated row/log entry is not a stale semantic input.
        for path in ("knowledge/wiki/index.md", "knowledge/wiki/log.md"):
            if path in revisions:
                revisions[path] = _file_digest(self._optional_text(self._safe_path(path, allow_missing=True)))
        self._assert_required_skill_revisions(payload["skill"], supplied, before, payload.get("moves", []), revisions)
        features = [path for path in supplied if path.startswith("knowledge/wiki/features/")]
        before_fm = {path: _parse_markdown(before[path], path)[0] if before[path] is not None else None for path in features}
        after_fm = {path: self._validate_feature_output(path, supplied[path], payload["skill"]) for path in features}
        current = self._validate_skill_semantics(actor, payload["skill"], supplied, before, before_fm, after_fm, payload.get("moves", []))
        if current.get("classification") != "ready" or current.get("blockers"):
            raise BoardError("checks_changed", "Current workflow checks no longer permit this skill operation; obtain a fresh preview.", 409)

    def _operation_file_states(self, intent: Mapping[str, Any]) -> list[dict[str, Any]]:
        states = []
        for write in intent.get("writes", []):
            current = self._optional_text(self._safe_path(write["path"], allow_missing=True))
            if current is None:
                current = self._intake_before_text(write["path"], intent.get("moves", []))
            digest = _file_digest(current)
            state = "applied" if digest == write.get("after_digest") else "pending" if digest == write.get("before_digest") else "conflict"
            merge = write.get("merge") or {}
            if write.get("role") == "index":
                rows = {key: self._index_existing_row(key) for key in merge.get("after_rows", {})}
                state = "applied" if rows == merge.get("after_rows") else "pending" if rows == merge.get("expected_rows") else "conflict"
            elif write.get("role") == "log":
                marker = f"<!-- prism:board-history:v1 {merge.get('marker')} -->"
                recorded = _append_once("", marker, merge.get("entry", ""))
                state = "applied" if recorded in (current or "") else "conflict" if marker in (current or "") else "pending"
            states.append({"path": write["path"], "state": state, "before": write.get("before"), "after": write.get("after"), "current_digest": digest})
        return states

    def _assert_index_rows(self, relative: str, expected: Mapping[str, Any]) -> None:
        content = self._read_text(self._safe_path(relative))
        for feature_id, row in expected.items():
            if self._index_existing_row(feature_id) != row:
                raise BoardError("stale_index_row", f"The index row for `{feature_id}` changed after preview.", 409)

    def _roll_forward(self, actor: Actor, operation_id: str, intent: Mapping[str, Any]) -> dict[str, Any]:
        store = self._require_store()
        conflicts: list[dict[str, Any]] = []
        conflict_paths: list[str] = []
        applied: list[str] = []
        moved: list[dict[str, str]] = []
        attribution: dict[str, Any] = {"actor": intent.get("actor")}
        if intent.get("recovery_attempts"):
            attribution["recovery_attempts"] = intent["recovery_attempts"]
        if actor.participant_id != intent.get("participant_id"):
            attribution["recovered_by"] = actor.to_dict()
        with self._lock:
            self._require_actor(actor, write=True)
            with store.read() as db:
                existing = db.execute(
                    "SELECT state, receipt_json FROM operations WHERE operation_id = ?", (operation_id,)
                ).fetchone()
            if existing is not None and existing[0] == "applied":
                return _loads(existing[1])
            self._assert_unresolved_writes_safe(operation_id, intent)
            try:
                states = self._operation_file_states(intent)
                for item in states:
                    if item["state"] == "conflict":
                        conflict_paths.append(item["path"])
                        raise BoardError("recovery_conflict", f"`{item['path']}` matches neither the recorded before-state nor after-state.", 409)
                move_states = [self._move_state(move, intent) for move in intent.get("moves", [])]
                complete = all(item["state"] == "applied" for item in states) and all(state == "applied" for state in move_states)
                if not complete:
                    self._assert_recovery_sources(intent, conflict_paths)
                    self._revalidate_recovery(actor, intent)
                    self._assert_recovery_sources(intent, conflict_paths)
                for move in intent.get("moves", []):
                    self._require_actor(actor, write=True)
                    source = self._safe_path(move["source"], allow_missing=True)
                    destination = self._safe_path(move["destination"], allow_missing=True)
                    if self._move_state(move, intent) == "pending":
                        self._assert_recovery_sources(intent, conflict_paths)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        self._reject_reparse(destination.parent, include_leaf=True)
                        self._require_actor(actor, write=True)
                        if self._move_state(move, intent) != "pending":
                            raise BoardError("recovery_conflict", "The intake tree changed immediately before its rename.", 409)
                        os.replace(source, destination)
                    moved.append({"source": move["source"], "destination": move["destination"]})
                if not complete:
                    for write in intent.get("writes", []):
                        self._require_actor(actor, write=True)
                        self._assert_recovery_sources(intent, conflict_paths)
                        result = self._apply_write(write, actor=actor)
                        if result == "conflict":
                            conflict_paths.append(write["path"])
                            conflicts.append({"path": write["path"], "reason": "current file matches neither the recorded before-state nor the proposed after-state"})
                            break
                        if result == "applied":
                            applied.append(write["path"])
            except BoardError as exc:
                if exc.code == "recovery_move_conflict":
                    conflict_paths.extend(path for move in intent.get("moves", []) for path in (move["source"], move["destination"]))
                conflicts.append({"path": None, "reason": f"{exc.code}: {exc.message}"})
            except OSError as exc:
                conflicts.append({"path": None, "reason": f"filesystem error: {type(exc).__name__}"})

            now = _now()
            if conflicts:
                receipt = {
                    **attribution,
                    "schema_version": 1,
                    "operation_id": operation_id,
                    "state": "conflict",
                    "applied_paths": applied,
                    "moved_folders": moved,
                    "conflicts": conflicts,
                    "recovery_available": True,
                }
                reported_paths = list(dict.fromkeys(conflict_paths))
                already_reported = False
                if existing is not None and existing[0] == "conflict":
                    with store.read() as db:
                        recorded = [
                            _loads(row[0])
                            for row in db.execute("SELECT event_json FROM events WHERE operation_id = ? ORDER BY cursor DESC", (operation_id,)).fetchall()
                        ]
                    last = next((event for event in recorded if event.get("type") == "operation-conflict"), None)
                    already_reported = last is not None and last.get("paths") == reported_paths
                with store.transaction() as db:
                    db.execute(
                        "UPDATE operations SET state = 'conflict', receipt_json = ?, updated_at = ? WHERE operation_id = ?",
                        (_json(receipt), now, operation_id),
                    )
                    if not already_reported:
                        db.execute(
                            "INSERT INTO events(operation_id, participant_id, event_json, created_at) VALUES (?, ?, ?, ?)",
                            (operation_id, actor.participant_id, _json({"type": "operation-conflict", "operation_id": operation_id, "paths": reported_paths}), now),
                        )
                return receipt

            receipt = {
                **attribution,
                "schema_version": 1,
                "operation_id": operation_id,
                "state": "applied",
                "preview_id": intent.get("preview_id"),
                "skill": intent.get("skill"),
                "action": intent.get("action"),
                "feature_id": intent.get("feature_id"),
                "applied_paths": [write["path"] for write in intent.get("writes", [])],
                "moved_folders": moved,
                "applied_at": now,
                "recovery_available": False,
            }
            with store.transaction() as db:
                db.execute(
                    "UPDATE operations SET state = 'applied', receipt_json = ?, updated_at = ? WHERE operation_id = ?",
                    (_json(receipt), now, operation_id),
                )
                db.execute(
                    "INSERT INTO events(operation_id, participant_id, event_json, created_at) VALUES (?, ?, ?, ?)",
                    (operation_id, actor.participant_id, _json({"type": "operation-applied", "receipt": receipt}), now),
                )
            return receipt

    def _move_state(self, move: Mapping[str, Any], intent: Mapping[str, Any]) -> str:
        """A rename is recoverable only while its entire recorded tree matches."""
        source = self._safe_path(move["source"], allow_missing=True)
        destination = self._safe_path(move["destination"], allow_missing=True)
        if source.exists():
            if destination.exists() or not source.is_dir() or self._tree_digest(source) != move["source_digest"]:
                raise BoardError("recovery_move_conflict", "The intake source changed or its destination already exists.", 409)
            return "pending"
        if not destination.is_dir():
            raise BoardError("recovery_move_conflict", "Both the recorded intake source and destination are missing.", 409)
        expected = dict(move.get("source_files", {}))
        allowed = {path: {digest} for path, digest in expected.items()}
        directories = set(move.get("source_directories", []))
        optional_directories: set[str] = set()
        prefix = move["destination"] + "/"
        for write in intent.get("writes", []):
            if not write["path"].startswith(prefix):
                continue
            relative = write["path"][len(prefix):]
            allowed.setdefault(relative, {None}).add(write["after_digest"])
            parent = PurePosixPath(relative).parent
            optional_directories.update(str(path) for path in (parent, *parent.parents) if str(path) != ".")
        actual = self._tree_snapshot(destination)
        if set(actual) - set(allowed) or any(actual.get(path) not in digests for path, digests in allowed.items()):
            raise BoardError("recovery_move_conflict", "The moved intake tree contains unrecorded or changed files.", 409)
        actual_directories = set(self._tree_directories(destination))
        if not directories <= actual_directories or actual_directories - directories - optional_directories:
            raise BoardError("recovery_move_conflict", "The moved intake tree contains changed directory structure.", 409)
        return "applied"

    def _assert_recovery_sources(self, intent: Mapping[str, Any], conflict_paths: list[str] | None = None) -> None:
        self.validate_graph_inputs()
        writes = {write["path"] for write in intent.get("writes", [])}
        moved_prefixes = []
        for move in intent.get("moves", []):
            self._move_state(move, intent)
            moved_prefixes.extend((move["source"], move["destination"]))
        for relative, expected in intent.get("source_map", {}).items():
            if relative in writes or any(relative == prefix or relative.startswith(prefix + "/") for prefix in moved_prefixes):
                continue
            actual = self._fingerprint_paths([relative])[relative]
            if actual != expected:
                if conflict_paths is not None:
                    conflict_paths.append(relative)
                raise BoardError("recovery_source_changed", f"Relevant source `{relative}` changed; recorded writes cannot be recovered automatically.", 409)
        for state in self._operation_file_states(intent):
            if state["state"] == "conflict":
                if conflict_paths is not None:
                    conflict_paths.append(state["path"])
                raise BoardError("recovery_conflict", f"`{state['path']}` changed during recovery.", 409)

    def _revalidate_recovery(self, actor: Actor, intent: Mapping[str, Any]) -> None:
        """Recheck current rules against a reconstructed before-state, off disk."""
        with tempfile.TemporaryDirectory(prefix="prism-board-recovery-") as directory:
            candidate_root = Path(directory)
            self._build_candidate_root(candidate_root, {}, [])
            intake = self._safe_path("knowledge/intake", allow_missing=True)
            if intake.is_dir():
                self._copy_tree_safely(intake, candidate_root / "knowledge/intake")
            for move in intent.get("moves", []):
                source, destination = candidate_root / move["source"], candidate_root / move["destination"]
                if not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    destination.rename(source)
            for write in intent.get("writes", []):
                if write["role"] == "log":
                    continue
                relative = write["path"]
                for move in intent.get("moves", []):
                    prefix = move["destination"] + "/"
                    if relative.startswith(prefix):
                        relative = move["source"] + "/" + relative[len(prefix):]
                        break
                target = candidate_root / relative
                if write["role"] == "index":
                    current = target.read_bytes().decode("utf-8")
                    before_rows = write["merge"]["expected_rows"]
                    absent = {key.casefold() for key, row in before_rows.items() if row is None}
                    current = "".join(line for line in current.splitlines(keepends=True) if not ((match := _INDEX_ROW.match(line.rstrip("\r\n"))) and match.group(1).casefold() in absent))
                    content = _render_index(current, {}, {key: row for key, row in before_rows.items() if row is not None})
                    target.write_bytes(content.encode("utf-8"))
                elif write.get("before") is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(write["before"].encode("utf-8"))
            with BoardService(candidate_root) as candidate:
                candidate._revalidate_operation(actor, intent)

    def _apply_write(self, write: Mapping[str, Any], *, actor: Actor | None = None) -> str:
        relative = self._relative_path(write["path"])
        path = self._safe_path(relative, allow_missing=True)
        role = write.get("role")
        merge = write.get("merge") or {}
        if role == "index":
            current = self._read_text(path)
            actual_rows = {feature_id: self._index_existing_row(feature_id) for feature_id in merge.get("after_rows", {})}
            if actual_rows == merge.get("after_rows"):
                return "already"
            if actual_rows != merge.get("expected_rows"):
                return "conflict"
            merged = _render_index(current, merge.get("expected_rows", {}), merge.get("after_rows", {}))
            self._atomic_replace(path, merged, expected=current, actor=actor)
            return "applied"
        if role == "log":
            current = self._optional_text(path)
            marker = f"<!-- prism:board-history:v1 {merge.get('marker')} -->"
            recorded = _append_once("", marker, merge.get("entry", ""))
            if recorded in (current or ""):
                return "already"
            if marker in (current or ""):
                return "conflict"
            merged = _append_once(current or "", marker, merge.get("entry", ""))
            self._atomic_replace(path, merged, expected=current, actor=actor)
            return "applied"
        current = self._optional_text(path)
        actual = _file_digest(current)
        if actual == write.get("after_digest"):
            return "already"
        if actual != write.get("before_digest"):
            return "conflict"
        self._atomic_replace(path, write.get("after", ""), expected=current, actor=actor)
        return "applied"

    def _atomic_replace(self, path: Path, content: str, *, expected: str | None, actor: Actor | None = None) -> None:
        self._reject_reparse(path.parent, include_leaf=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._reject_reparse(path.parent, include_leaf=True)
        self._reject_reparse(path, include_leaf=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=".prism-write-", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._reject_reparse(path, include_leaf=True)
            if actor is not None:
                self._require_actor(actor, write=True)
            if self._optional_text(path) != expected:
                raise BoardError("write_changed", f"`{path.relative_to(self.root).as_posix()}` changed immediately before replacement.", 409)
            os.replace(temp_path, path)
            try:
                directory_fd = os.open(path.parent, getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
            except OSError:
                return
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _assert_unresolved_writes_safe(self, current_operation: str, intent: Mapping[str, Any]) -> None:
        store = self._require_store()

        def targets(payload):
            paths = {write["path"] for write in payload.get("writes", []) if write.get("role") not in {"index", "log"}}
            for move in payload.get("moves", []):
                paths.update((move["source"], move["destination"]))
            keys = {key.casefold() for write in payload.get("writes", []) if write.get("role") == "index" for key in write["merge"]["after_rows"]}
            return paths, keys

        def overlaps(left, right):
            return any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in left for b in right)

        paths, keys = targets(intent)
        with store.read() as db:
            rows = db.execute(
                "SELECT operation_id, intent_json FROM operations WHERE state IN ('pending', 'conflict') AND operation_id != ?",
                (current_operation,),
            ).fetchall()
        for operation_id, raw in rows:
            other = _loads(raw)
            other_paths, other_keys = targets(other)
            if keys & other_keys or overlaps(paths, other_paths) or overlaps(paths, other.get("source_map", {})) or overlaps(other_paths, intent.get("source_map", {})):
                raise BoardError("unresolved_operation_overlap", f"Operation `{operation_id}` has unresolved writes that overlap this operation.", 409)


from prism_cli.wiki_transitions import ACTION_SPECS as _REGISTERED_ACTION_SPECS

_ACTION_BY_NAME = {
    spec.action: {
        "source_status": spec.source_status,
        "source_owner": spec.source_owner,
        "target_status": spec.target_status,
        "target_owner": spec.target_owner,
        "command": spec.command,
    }
    for spec in _REGISTERED_ACTION_SPECS
}


def BoardServiceIdentity(root: Path) -> tuple[Any, ...] | None:
    """Read current workflow identity and project scope, including asset pin."""

    try:
        workspace_root = Path(root).expanduser().absolute()
        manifest_path = workspace_root / "prism.workspace.yml"
        BoardService._reject_reparse(manifest_path, include_leaf=True)
        for relative in ("knowledge/wiki/SCHEMA.md", "knowledge/wiki/index.md"):
            BoardService._reject_reparse(workspace_root / relative, include_leaf=True)
        if not (workspace_root / "knowledge/wiki/SCHEMA.md").is_file() or not (workspace_root / "knowledge/wiki/index.md").is_file():
            return None
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig")) or {}
        workflow = data.get("workflow") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not isinstance(workflow, dict):
            return None
        schema_version = data.get("schema_version")
        if type(schema_version) is not int or schema_version != 1:
            return None
        from prism_cli.workflow_assets import asset_digest

        digest = asset_digest(version="1")
        board_id = str(UUID(workflow.get("board_id")))
        version = workflow.get("version")
        mode = workflow.get("mode")
        stored_digest = workflow.get("asset_digest")
        project = data.get("project")
        if not isinstance(project, dict) or version != "1" or mode not in {"workflow", "generated"} or stored_digest != digest:
            return None
        project_name = project.get("name")
        platforms = project.get("platforms")
        if (
            not isinstance(project_name, str)
            or not project_name.strip()
            or not isinstance(platforms, list)
            or not platforms
            or any(not isinstance(item, str) or item not in _SUPPORTED_PLATFORMS for item in platforms)
            or len(set(platforms)) != len(platforms)
        ):
            return None
        manifest_metadata = _manifest_identity_metadata(data, manifest_path)
        if manifest_metadata is None:
            return None
        return (board_id, "1", mode, digest, project_name.strip(), tuple(platforms), schema_version, manifest_metadata)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, TypeError, AttributeError, ImportError):
        return None


def _manifest_identity_metadata(data: Mapping[str, Any], manifest_path: Path | None = None) -> tuple[Any, ...] | None:
    """Validate and bind schema fields that affect workspace scope diagnostics."""

    if _minimum_cli_version_error(data, manifest_path or Path("prism.workspace.yml")) is not None:
        return None

    paths = data.get("paths", {})
    if paths is None:
        paths = {}
    if not isinstance(paths, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in paths.items()):
        return None
    if any(key in paths and paths[key] != value for key, value in _CANONICAL_MANIFEST_PATHS.items()):
        return None

    expected_surfaces = data.get("expected_surfaces", {})
    if expected_surfaces is None:
        expected_surfaces = {}
    if (
        not isinstance(expected_surfaces, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            for key, values in expected_surfaces.items()
        )
    ):
        return None

    min_version = data.get("min_prism_cli_version")
    if min_version is not None and not isinstance(min_version, str):
        return None
    paths_fact = tuple(sorted(paths.items()))
    surfaces_fact = tuple(sorted((key, tuple(values)) for key, values in expected_surfaces.items()))
    return paths_fact, surfaces_fact, min_version


def _minimum_cli_version_error(data: Mapping[str, Any], manifest_path: Path) -> str | None:
    """Use workspace's canonical shape and runtime checks for CLI minimums."""

    from prism_cli.workspace import WorkspaceManifest, _compare_manifest_runtime, _validate_manifest_shape

    checks = (
        *_validate_manifest_shape(data, manifest_path),
        *_compare_manifest_runtime(WorkspaceManifest(path=manifest_path, data=dict(data))),
    )
    minimum_codes = {"invalid-min-prism-cli-version", "minimum-prism-cli-version-not-met"}
    return next((item.message for item in checks if item.code in minimum_codes), None)


def _safe_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise BoardError("invalid_identifier", f"`{name}` must be a bounded opaque identifier.", 400)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_digest(content: str | None) -> str | None:
    return _sha256(content.encode("utf-8")) if content is not None else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _revision(entries: Mapping[str, Any]) -> str:
    return _sha256(_json(dict(sorted(entries.items()))).encode("utf-8"))


def _parse_markdown(content: str, path: str | None = None) -> tuple[dict[str, Any], str]:
    where = f" `{path}`" if path else ""
    base: dict[str, Any] = {"path": path} if path else {}
    match = _FRONTMATTER.match(content)
    if not match:
        raise BoardError(
            "invalid_markdown",
            f"Proposed wiki page{where} must start with a `---` line, then the YAML mapping of frontmatter fields, then a closing `---` line before the Markdown body.",
            409,
            {**base, "problem": "missing opening or closing `---` frontmatter delimiter"},
        )
    try:
        loaded = yaml.safe_load(match.group(1)) or {}
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        text = getattr(exc, "problem", None) or (str(exc).splitlines() or [type(exc).__name__])[0]
        problem = _clip(text, 120)
        details: dict[str, Any] = {**base, "problem": problem}
        position = ""
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            # The frontmatter block starts on file line 2, right after the opening `---`.
            details["line"] = mark.line + 2
            details["column"] = mark.column + 1
            position = f" at line {details['line']}, column {details['column']}"
        raise BoardError(
            "invalid_frontmatter",
            f"Proposed wiki page{where} has invalid YAML frontmatter{position}: {problem}. Fix the YAML between the opening and closing `---` lines; quote values that contain `: ` or start with a special character.",
            409,
            details,
        ) from exc
    if not isinstance(loaded, dict):
        kind = type(loaded).__name__
        raise BoardError(
            "invalid_frontmatter",
            f"Proposed YAML frontmatter{' in' + where if where else ''} must be a mapping of `field: value` lines, not a {kind}.",
            409,
            {**base, "problem": f"frontmatter is a {kind}, not a mapping"},
        )
    from prism_cli.wiki_model import parse_iso_date

    for field in ("introduced", "last-updated", "date"):
        normalized = parse_iso_date(loaded.get(field))
        if normalized is not None:
            loaded[field] = normalized.isoformat()
    return loaded, match.group(2)


def _section(body: str, heading: str) -> str:
    wanted = heading.strip().casefold()
    lines = body.splitlines(keepends=True)
    start: int | None = None
    for index, line in enumerate(lines):
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line.rstrip("\r\n"))
        if match and match.group(1).strip().casefold() == wanted:
            start = index + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(r"^##\s+", lines[index]):
            end = index
            break
    return "".join(lines[start:end])


def _strip_section(body: str, heading: str) -> str:
    wanted = heading.strip().casefold()
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line.rstrip("\r\n"))
        if match:
            skipping = match.group(1).strip().casefold() == wanted
        if not skipping:
            out.append(line)
    return "".join(out)


def _first_line_difference(old: str, new: str) -> tuple[str, str] | None:
    """The first pair of lines that differ between two texts (an absent line is empty), or None when only whitespace differs."""

    old_lines, new_lines = old.splitlines(), new.splitlines()
    for index in range(max(len(old_lines), len(new_lines))):
        left = old_lines[index].rstrip() if index < len(old_lines) else ""
        right = new_lines[index].rstrip() if index < len(new_lines) else ""
        if left != right:
            return left, right
    return None


def _body_without_sections(body: str, headings: set[str]) -> str:
    wanted = {heading.strip().casefold() for heading in headings}
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line.rstrip("\r\n"))
        if match:
            skipping = match.group(1).strip().casefold() in wanted
        if not skipping:
            out.append(line)
    return "".join(out)


def _table_rows(section: str, *, expected_columns: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != expected_columns or not all(cells):
            continue
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        if any(cell.casefold() in {"platform", "implementation", "tests", "release"} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _require_headings(body: str, headings: Iterable[str], relative: str, hint: str = "") -> None:
    missing = [heading for heading in headings if not _section(body, heading).strip()]
    if missing:
        raise BoardError(
            "required_section_missing",
            f"`{relative}` requires substantive sections: {', '.join(missing)}.{hint}",
            409,
            {"path": relative, "sections": _names(missing)} if hint else None,
        )


_API_ENDPOINT = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b[\s`*|:()\[\]-]*(/[A-Za-z0-9_\-./{}:~%]*)")
_API_SURFACE_PATH = re.compile(r"(?<![\w/.:])(/[A-Za-z0-9_\-./{}:~%]*[A-Za-z0-9_}])")


def _api_path_key(path: str) -> str:
    """A path with its case, query, trailing slash and parameter names normalized, so `/a/{id}` equals `/A/:x/`."""

    segments = [part for part in path.split("?")[0].split("#")[0].strip().rstrip(".,;:").lower().split("/") if part]
    return "/" + "/".join("{}" if part.startswith(("{", ":")) else part for part in segments)


def _api_word(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _api_contract_scope_error(relative: str, feature_id: str, body: str, surface: str) -> BoardError | None:
    """Check that a new contract's endpoints and models stay within the feature's API surface; None when they do.

    Endpoints are the `METHOD /path` entries of `## Endpoints`. When the API surface names paths, every endpoint
    must be one of them; otherwise each endpoint needs a resource word that the API surface text uses. A data model
    (a heading or a leading bold or code name in `## Data models`) must be named by the API surface or an endpoint.
    This is a structural traceability check; the reviewer still confirms that the contract says what the API surface means.
    """

    endpoints_text = _section(body, "Endpoints")
    endpoints: list[tuple[str, str]] = []
    for method, path in _API_ENDPOINT.findall(endpoints_text):
        entry = (method, _api_path_key(path))
        if entry not in endpoints:
            endpoints.append(entry)
    if not endpoints:
        return BoardError(
            "invalid_api_contract",
            f"API contract `{relative}` must list each endpoint under `## Endpoints` as `METHOD /path`, for example `POST /exports`.",
            409,
            {"path": relative, "section": "Endpoints"},
        )
    surface_paths = {_api_path_key(path) for path in _API_SURFACE_PATH.findall(surface)}
    surface_words = {_api_word(word) for word in re.findall(r"[a-z0-9]+", surface.lower())}
    untraced: list[str] = []
    for method, key in endpoints:
        if surface_paths:
            traced = key in surface_paths
        else:
            words = [
                _api_word(word)
                for part in key.split("/")
                if part and part != "{}" and part != "api" and not re.fullmatch(r"v\d+", part)
                for word in re.findall(r"[a-z0-9]+", part)
            ]
            traced = any(word in surface_words for word in words)
        if not traced:
            untraced.append(f"{method} {key}")
    if untraced:
        if surface_paths:
            fix = f"The API surface names only {_quoted(sorted(surface_paths)[:6])}; list endpoints with those paths."
        else:
            fix = "Each endpoint path needs a resource word that the API surface uses; an endpoint the API surface does not state must be added there first (route a question, then `po-clarify` or `dev-clarify`)."
        return BoardError(
            "api_contract_untraceable",
            f"API contract `{relative}` lists endpoint(s) {_quoted(untraced[:6])} that the `## API surface` of {feature_id} does not support. {fix}",
            409,
            {"path": relative, "feature_id": feature_id, "endpoints": [_clip(item, 120) for item in untraced[:10]]},
        )
    models_text = _section(body, "Data models")
    headings = re.findall(r"(?m)^#{3,6}\s+(.+?)\s*#*\s*$", models_text)
    names = headings or re.findall(r"(?m)^[-*+]\s+(?:\*\*|`)([^*`\n]+)(?:\*\*|`)", models_text)
    haystack = re.sub(r"[^a-z0-9]", "", (surface + endpoints_text).lower())
    unreferenced: list[str] = []
    for name in names:
        cleaned = re.sub(r"\(.*?\)", "", name).strip().rstrip(":").strip()
        key = re.sub(r"[^a-z0-9]", "", cleaned.lower())
        if key and key not in haystack and cleaned not in unreferenced:
            unreferenced.append(cleaned)
    if unreferenced:
        return BoardError(
            "api_contract_untraceable",
            f"API contract `{relative}` defines data model(s) {_quoted([_clip(item, 60) for item in unreferenced[:6]])} that neither the `## API surface` of {feature_id} "
            "nor any listed endpoint names. Remove them, or name them in the endpoint's request or response.",
            409,
            {"path": relative, "feature_id": feature_id, "models": [_clip(item, 60) for item in unreferenced[:10]]},
        )
    return None


def _validate_no_placeholders(body: str, relative: str) -> None:
    patterns = (
        re.compile(r"\b(?:TODO|TBD|FIXME)\b", re.IGNORECASE),
        re.compile(r"\[\s*(?:what\b|persona from|business outcome|condition \d+|feature name|persona name|platform\b|title\b|reason\b|YYYY-MM-DD|F-XXX|one paragraph|specific, actionable|list of|if known|answer\b|source\b)", re.IGNORECASE),
        re.compile(r"\bplaceholder\b", re.IGNORECASE),
    )
    if any(pattern.search(body) for pattern in patterns):
        raise BoardError("template_placeholder", f"`{relative}` contains unresolved template placeholder text.", 409)


def _index_row(frontmatter: Mapping[str, Any]) -> dict[str, str]:
    feature_id = frontmatter.get("id")
    title = frontmatter.get("title")
    status = frontmatter.get("status")
    owner = frontmatter.get("owner")
    advisory = frontmatter.get("advisory-review")
    introduced = frontmatter.get("introduced")
    if not all(isinstance(value, str) and value.strip() for value in (feature_id, title, status, owner, advisory, introduced)):
        raise BoardError("invalid_index_fields", "Feature index fields id, title, status, owner, advisory-review, and introduced are required.", 409)
    return {
        "id": feature_id.strip(),
        "title": re.sub(r"\s+", " ", title.strip()).replace("|", "&#124;"),
        "status": status.strip(),
        "owner": owner.strip(),
        "advisory_review": advisory.strip(),
        "introduced": introduced.strip(),
    }


def _index_row_from_match(match: re.Match[str]) -> dict[str, str]:
    return {
        "id": match.group(1).strip(),
        "title": match.group(2).strip(),
        "status": match.group(3).strip(),
        "owner": match.group(4).strip(),
        "advisory_review": match.group(5).strip(),
        "introduced": match.group(6).strip(),
    }


def _format_index_row(row: Mapping[str, str]) -> str:
    return f"| {row['id']} | {row['title']} | {row['status']} | {row['owner']} | {row['advisory_review']} | {row['introduced']} |"


def _render_index(content: str, expected: Mapping[str, Any], after: Mapping[str, Mapping[str, str]]) -> str:
    lines = content.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in content else "\n"
    header_index = next((i for i, line in enumerate(lines) if re.match(r"^\s*\|\s*ID\s*\|\s*Feature\s*\|\s*Status\s*\|", line, re.IGNORECASE)), None)
    if header_index is None or header_index + 1 >= len(lines) or "---" not in lines[header_index + 1]:
        raise BoardError("invalid_index", "knowledge/wiki/index.md must contain the canonical feature status table.", 409)
    end = header_index + 2
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    wanted = {key.casefold(): row for key, row in after.items()}
    found: set[str] = set()
    for index in range(header_index + 2, end):
        match = _INDEX_ROW.match(lines[index].rstrip("\r\n"))
        if not match:
            continue
        key = match.group(1).casefold()
        if key in wanted:
            ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
            lines[index] = _format_index_row(wanted[key]) + ending
            found.add(key)
    missing = [row for key, row in wanted.items() if key not in found]
    if missing:
        insertion = end
        if insertion and not lines[insertion - 1].endswith("\n"):
            lines[insertion - 1] += newline
        for offset, row in enumerate(sorted(missing, key=lambda item: int(re.search(r"\d+", item["id"]).group(0)))):
            lines.insert(insertion + offset, _format_index_row(row) + newline)
    return "".join(lines)


def _actor_log_entry(actor: Actor, action: str, subject: str, preview_id: str) -> str:
    clean_subject = re.sub(r"[\r\n]+", " ", subject).strip()[:180] or "workflow"
    safe_action = re.sub(r"[^a-z0-9-]", "-", action.lower())[:64]
    actor_payload = {
        "participant_id": actor.participant_id,
        "kind": actor.kind,
        "name": actor.name,
        "preview_id": preview_id,
        "action": action,
    }
    return (
        f"## {date.today().isoformat()} [board-{safe_action}] | {clean_subject}\n"
        f"<!-- prism:board-actor:v1 {_json(actor_payload)} -->"
    )


def _append_once(existing: str, marker: str, entry: str) -> str:
    if marker in existing:
        return existing
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + marker + "\n" + entry.rstrip() + "\n"


def _classification(checks: Iterable[Mapping[str, Any]]) -> str:
    statuses = [item.get("status") for item in checks]
    if "unknown" in statuses:
        return "unknown"
    if "blocked" in statuses or "review" in statuses:
        return "blocked"
    return "ready"


_ARCHIVE_LABEL = "Prior completion/release evidence"
_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s")


def _label_block(text: str, label: str, labels: Iterable[str]) -> str:
    """The text of one reopen-record label: its own line and the lines below it.

    The block ends at the next labelled bullet or heading, so evidence rows may
    follow the label on the lines beneath it as a list or a table.
    """

    head = re.compile(rf"(?i)^\s*-\s*{re.escape(label)}:[ \t]*(.*)$")
    next_label = re.compile(r"(?i)^\s*-\s*(?:" + "|".join(re.escape(item) for item in labels) + r"):")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        found = head.match(line)
        if found:
            break
    else:
        return ""
    block = [found.group(1).strip()]
    for line in lines[index + 1:]:
        if next_label.match(line) or _HEADING_LINE.match(line):
            break
        block.append(line)
    return "\n".join(block).strip()


def _normalized_table_text(text: str) -> str:
    """Case-folded text with whitespace collapsed and no space around table pipes."""

    return re.sub(r"\s*\|\s*", "|", re.sub(r"\s+", " ", text)).strip().casefold()


def _page_feature_id(content: str, filename: str) -> str | None:
    try:
        frontmatter, _body = _parse_markdown(content)
    except BoardError:
        frontmatter = {}
    value = frontmatter.get("feature-id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    match = re.match(r"^(F-\d+)", filename, re.IGNORECASE)
    return match.group(1) if match else None


def _move_subject(moves: Iterable[Mapping[str, Any]]) -> str:
    for move in moves:
        parts = PurePosixPath(str(move.get("source", ""))).parts
        if parts:
            return parts[-1]
    return "intake"


def _reparse_point(info: os.stat_result) -> bool:
    return reparse_kind(info) != "none"
