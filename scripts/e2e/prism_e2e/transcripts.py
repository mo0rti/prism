"""Read what a host recorded: tool calls, errors, final message, model, effort and usage.

Model and effort come from the host's own records, never from the command
line: Claude Code's session file records ``effort`` and ``perTurnEffort``;
Codex's rollout records the model and effort in ``turn_context``. Both parsers
accept the streams the hosts print with ``--output-format stream-json`` and
``exec --json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import glob
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

PREVIEW_TOOLS = ("preview_skill", "preview_transition")
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ERROR_CODE = re.compile(r"tool \w+: (\w+):")


@dataclass
class ToolCall:
    name: str
    ok: bool = True
    error_code: str | None = None
    error_text: str | None = None
    result: dict[str, Any] | None = None  # the parsed JSON result of a successful call


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_tokens += other.reasoning_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


@dataclass
class HostTranscript:
    host: str
    calls: list[ToolCall] = field(default_factory=list)
    final_message: str = ""
    models: set[str] = field(default_factory=set)
    session_id: str | None = None  # Claude session ID or Codex thread ID
    usage: Usage | None = None
    cost_usd: float | None = None
    host_error: str | None = None
    complete: bool = False  # the host's closing event was seen
    billed_models: list[str] = field(default_factory=list)  # every model the host billed, auxiliary ones included

    def calls_named(self, *names: str) -> list[ToolCall]:
        return [call for call in self.calls if call.name in names]

    @property
    def preview_calls(self) -> list[ToolCall]:
        return self.calls_named(*PREVIEW_TOOLS)

    def successful_preview_ids(self) -> list[str]:
        ids: list[str] = []
        for call in self.preview_calls:
            if call.ok and call.result and isinstance(call.result.get("preview_id"), str):
                ids.append(call.result["preview_id"])
        return ids


def error_code(text: str | None) -> str:
    """The service's error code from ``Error executing tool <tool>: <code>: <message>``, else ``error``."""

    match = _ERROR_CODE.search(text or "")
    return match.group(1) if match else "error"


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _json_or_none(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _events(text: str) -> Iterable[dict[str, Any]]:
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def parse_claude_stream(text: str) -> HostTranscript:
    transcript = HostTranscript(host="claude")
    pending: dict[str, ToolCall] = {}
    last_assistant_text = ""
    for event in _events(text):
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            transcript.session_id = event.get("session_id") or transcript.session_id
            if event.get("model"):
                transcript.models.add(event["model"])
        elif kind == "assistant":
            message = event.get("message") or {}
            if message.get("model"):
                transcript.models.add(message["model"])
            for block in message.get("content") or []:
                if block.get("type") == "tool_use" and block.get("id") not in pending:
                    name = str(block.get("name", "")).removeprefix("mcp__prism__")
                    call = ToolCall(name=name)
                    pending[block["id"]] = call
                    transcript.calls.append(call)
                elif block.get("type") == "text" and block.get("text"):
                    last_assistant_text = block["text"]
        elif kind == "user":
            content = (event.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") != "tool_result" or block.get("tool_use_id") not in pending:
                    continue
                call = pending[block["tool_use_id"]]
                body = _text_of(block.get("content"))
                if block.get("is_error"):
                    call.ok = False
                    call.error_text = body
                    call.error_code = error_code(body)
                else:
                    call.result = _json_or_none(body)
        elif kind == "result":
            transcript.complete = True
            transcript.final_message = str(event.get("result") or "")
            if event.get("is_error"):
                transcript.host_error = str(event.get("subtype") or "error")
            usage = event.get("usage") or {}
            transcript.usage = Usage(
                input_tokens=int(usage.get("input_tokens") or 0),
                cached_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                reasoning_tokens=int((usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0),
            )
            if isinstance(event.get("total_cost_usd"), (int, float)):
                transcript.cost_usd = float(event["total_cost_usd"])
            transcript.billed_models = sorted(event.get("modelUsage") or {})
    if not transcript.final_message:
        transcript.final_message = last_assistant_text
    return transcript


def parse_codex_stream(text: str, last_message: str | None = None) -> HostTranscript:
    transcript = HostTranscript(host="codex")
    usage = Usage()
    saw_usage = False
    last_agent_text = ""
    for event in _events(text):
        kind = event.get("type")
        if kind == "thread.started":
            transcript.session_id = event.get("thread_id")
        elif kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                last_agent_text = str(item.get("text") or "")
            elif item.get("type") == "mcp_tool_call":
                call = ToolCall(name=str(item.get("tool", "")))
                result = item.get("result") or {}
                body = _text_of(result.get("content"))
                structured = result.get("structured_content")
                if item.get("status") == "failed" or item.get("error"):
                    call.ok = False
                    call.error_text = body or json.dumps(item.get("error"))
                    call.error_code = error_code(call.error_text)
                else:
                    call.result = structured if isinstance(structured, dict) else _json_or_none(body)
                transcript.calls.append(call)
        elif kind == "turn.completed":
            transcript.complete = True
            found = event.get("usage") or {}
            saw_usage = True
            usage.add(
                Usage(
                    input_tokens=int(found.get("input_tokens") or 0),
                    cached_input_tokens=int(found.get("cached_input_tokens") or 0),
                    cache_creation_tokens=int(found.get("cache_write_input_tokens") or 0),
                    output_tokens=int(found.get("output_tokens") or 0),
                    reasoning_tokens=int(found.get("reasoning_output_tokens") or 0),
                )
            )
        elif kind in ("turn.failed", "error"):
            message = event.get("message") or (event.get("error") or {}).get("message") or kind
            transcript.host_error = str(message)
    transcript.usage = usage if saw_usage else None
    transcript.final_message = (last_message or "").strip() or last_agent_text
    return transcript


# --- the hosts' own session records ---------------------------------------------


def claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def claude_session_efforts(session_id: str | None, config_dir: Path | None = None) -> set[str]:
    """Effort values Claude Code recorded for a session (``effort`` and ``perTurnEffort``)."""

    if not session_id:
        return set()
    base = config_dir or claude_config_dir()
    efforts: set[str] = set()
    for path in glob.glob(str(base / "projects" / "*" / f"{session_id}.jsonl")):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                efforts.update(re.findall(r'"(?:effort|perTurnEffort)": ?"(\w+)"', line))
    return efforts


def claude_session_models(session_id: str | None, config_dir: Path | None = None) -> set[str]:
    if not session_id:
        return set()
    base = config_dir or claude_config_dir()
    models: set[str] = set()
    for path in glob.glob(str(base / "projects" / "*" / f"{session_id}.jsonl")):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                message = event.get("message") if isinstance(event, dict) else None
                if isinstance(message, dict) and message.get("model") and event.get("type") == "assistant":
                    models.add(message["model"])
    return models


def codex_rollout_model_effort(thread_id: str | None, home: Path | None = None) -> tuple[set[str], set[str]]:
    """Models and efforts a Codex rollout recorded in ``turn_context``."""

    if not thread_id:
        return set(), set()
    base = home or codex_home()
    models: set[str] = set()
    efforts: set[str] = set()
    for path in glob.glob(str(base / "sessions" / "*" / "*" / "*" / f"rollout-*{thread_id}.jsonl")):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"turn_context"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") != "turn_context":
                    continue
                payload = event.get("payload") or {}
                if payload.get("model"):
                    models.add(str(payload["model"]))
                settings = (payload.get("collaboration_mode") or {}).get("settings") or {}
                effort = payload.get("effort") or settings.get("reasoning_effort")
                if effort:
                    efforts.add(str(effort))
    return models, efforts


def model_matches(expected: str, recorded: Iterable[str]) -> bool:
    """True when every recorded model is the expected one or a dated build of it (``claude-haiku-4-5-20251001``)."""

    recorded = [model for model in recorded if model]
    if not recorded:
        return False
    return all(model == expected or re.fullmatch(re.escape(expected) + r"-\d{8}", model) for model in recorded)


def collapse_models(models: Iterable[str]) -> list[str]:
    """Sorted model IDs without an alias that a dated build in the same set already names (``claude-haiku-4-5`` next to ``claude-haiku-4-5-20251001``)."""

    unique = sorted({model for model in models if model})
    return [model for model in unique if not any(other != model and re.fullmatch(re.escape(model) + r"-\d{8}", other) for other in unique)]


def first_reported_preview_id(message: str, known_ids: Iterable[str]) -> str | None:
    """The first ID in the agent's message that is a preview its own tool calls returned."""

    known = set(known_ids)
    for candidate in UUID_PATTERN.findall(message or ""):
        if candidate in known:
            return candidate
    return None
