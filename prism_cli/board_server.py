"""Authenticated local HTTP and MCP transport for the Prism board.

The HTTP routes and MCP tools are adapters only: every workflow decision is
delegated to one shared BoardService instance.  The optional ASGI dependencies
are loaded by ``create_app`` so unrelated CLI commands remain importable
without the transport extra.
"""

from __future__ import annotations

import asyncio
import errno
import functools
import hashlib
import hmac
import itertools
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


DEFAULT_BOARD_PORT = 8765
MAX_REQUEST_BYTES = 1_048_576
SESSION_TTL_SECONDS = 43_200
GRAPH_POLL_SECONDS = 1.5
SESSION_RECHECK_SECONDS = 15.0
# How often an open event stream checks whether the server is shutting down.
STREAM_STOP_CHECK_SECONDS = 0.25
# Longest an interrupt waits for open connections before they are cancelled.
SHUTDOWN_GRACE_SECONDS = 5
API_PREFIX = "/api/board/v1"


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class GraphUnavailable(Exception):
    """The workspace graph inputs failed their service safety check."""


@dataclass
class _Session:
    token: str
    csrf: str
    participant_id: Any
    board_id: Any
    workflow_version: Any
    kind: str
    expires_at: float


class _LiveGraph:
    """One background poller shared by graph snapshots and SSE clients."""

    def __init__(self, root: Path, validate_inputs: Callable[[], None]) -> None:
        from prism_cli.wiki_graph import build_graph
        from prism_cli.wiki_transitions import FingerprintCache, workspace_fingerprint

        self.root = root
        self._validate_inputs = validate_inputs
        self._build_graph: Callable[[Path], dict[str, Any]] = build_graph
        # The graph snapshot and version reuse file hashes between scans: this poller and the
        # refresh that follows an apply or recover request share the cache. Stale-preview and
        # apply decisions and `query` hash every file themselves and never read it.
        self._fingerprint_fn: Callable[[Path], Any] = functools.partial(workspace_fingerprint, cache=FingerprintCache())
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.epoch = uuid.uuid4().hex
        self.version = 1
        self.valid = False
        self._validate_inputs()
        self.fingerprint = self._fingerprint_fn(root)
        self.envelope = self._build_graph(root)
        self._validate_inputs()
        self.valid = True

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, name="prism-board-graph", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3)
        self._thread = None

    def _poll(self) -> None:
        while not self._stop.wait(GRAPH_POLL_SECONDS):
            self.refresh_now()

    def refresh_now(self) -> None:
        """Rebuild the snapshot now when the workspace changed since the last one.

        The poller and the write path share this. It reuses the fingerprint, so
        an unchanged workspace costs one fingerprint read and no graph build.
        """

        try:
            self._validate_inputs()
            fingerprint = self._fingerprint_fn(self.root)
            with self._lock:
                if fingerprint == self.fingerprint and self.valid:
                    return
                self._validate_inputs()
                envelope = self._build_graph(self.root)
                self._validate_inputs()
                self.envelope = envelope
                self.fingerprint = fingerprint
                self.version += 1
                self.valid = True
        except Exception:
            # A failed refresh leaves the last known graph intact.  The
            # next shared poll retries.  Mark it unavailable so no stale
            # snapshot masks an unsafe current workspace tree.
            with self._lock:
                self.valid = False

    def snapshot(self) -> tuple[str, int, dict[str, Any]]:
        with self._lock:
            if not self.valid:
                raise GraphUnavailable
            return self.epoch, self.version, self.envelope


class _SnapshotRefreshingService:
    """Delegate to the shared BoardService and refresh the graph snapshot as soon
    as a write call returns, so the next /data.json read and the next event
    already include the write. HTTP and MCP both call through this wrapper.
    The poller still covers edits made outside the service."""

    _WRITE_METHODS = frozenset({"apply", "recover"})

    def __init__(self, service: Any, graph: _LiveGraph) -> None:
        self._service = service
        self._graph = graph

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._service, name)
        if name not in self._WRITE_METHODS or not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            from prism_cli.wiki_model import wiki_read_scope

            # One request: the write and the graph refresh that follows it share
            # parsed pages, and the scope ends when the request does.
            with wiki_read_scope():
                try:
                    return attribute(*args, **kwargs)
                finally:
                    # Runs after the service releases its lock; never raises.
                    self._graph.refresh_now()

        return call


class _BoundaryMiddleware:
    """Validate local host/origin/credential boundaries and cap request bodies."""

    def __init__(self, app: Any, *, port: int, cookie_name: str, max_bytes: int) -> None:
        self.app = app
        self.port = port
        self.cookie_name = cookie_name.encode("ascii")
        self.max_bytes = max_bytes
        self.allowed_hosts = {
            f"127.0.0.1:{port}".encode("ascii"),
            f"localhost:{port}".encode("ascii"),
        }
        if port == 80:
            self.allowed_hosts.update({b"127.0.0.1", b"localhost"})

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers", [])
        host_values = [value.lower() for name, value in raw_headers if name.lower() == b"host"]
        origin_values = [value for name, value in raw_headers if name.lower() == b"origin"]
        auth_values = [value for name, value in raw_headers if name.lower() == b"authorization"]
        cookie_values = [value for name, value in raw_headers if name.lower() == b"cookie"]
        csrf_values = [value for name, value in raw_headers if name.lower() == b"x-prism-csrf"]
        content_type_values = [value for name, value in raw_headers if name.lower() == b"content-type"]
        host = host_values[0] if len(host_values) == 1 else b""
        fetch_sites = [value.lower() for name, value in raw_headers if name.lower() == b"sec-fetch-site"]
        bad = (
            host not in self.allowed_hosts
            or len(origin_values) > 1
            or len(auth_values) > 1
            or len(cookie_values) > 1
            or len(csrf_values) > 1
            or len(content_type_values) > 1
            or len(fetch_sites) > 1
            or (origin_values and not self._valid_origin(origin_values[0], host))
            or (fetch_sites and fetch_sites[0] not in {b"same-origin", b"none"})
        )
        board_cookie_present = any(
            any(part.split(b"=", 1)[0].strip() == self.cookie_name for part in value.split(b";"))
            for value in cookie_values
        )
        if auth_values and board_cookie_present:
            bad = True
        if bad:
            await _send_json(send, 400, {"error": {"code": "local_origin_required", "message": "Use the local same-origin Prism board address."}})
            return

        content_lengths = [value for name, value in raw_headers if name.lower() == b"content-length"]
        if len(content_lengths) > 1:
            await _send_json(send, 400, {"error": {"code": "invalid_content_length", "message": "The request is malformed."}})
            return
        if content_lengths:
            try:
                if not content_lengths[0].isdigit():
                    raise ValueError
                declared = int(content_lengths[0])
            except (TypeError, ValueError):
                await _send_json(send, 400, {"error": {"code": "invalid_content_length", "message": "The request is malformed."}})
                return
            if declared < 0:
                await _send_json(send, 400, {"error": {"code": "invalid_content_length", "message": "The request is malformed."}})
                return
            if declared > self.max_bytes:
                await _send_json(send, 413, {"error": {"code": "request_too_large", "message": "The request is too large."}})
                return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await _send_json(send, 413, {"error": {"code": "request_too_large", "message": "The request is too large."}})
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        replayed = False

        async def replay_body() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)

    def _valid_origin(self, raw: bytes, host: bytes) -> bool:
        try:
            origin = raw.decode("ascii")
            parsed = urlsplit(origin)
            return (
                parsed.scheme == "http"
                and parsed.netloc.encode("ascii").lower() == host
                and parsed.path == ""
                and not parsed.query
                and not parsed.fragment
                and parsed.username is None
                and parsed.password is None
            )
        except (UnicodeError, ValueError):
            return False


class _SecurityHeadersMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        async def add_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {name.lower() for name, _value in headers}
                secure = [
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"),
                    (b"x-frame-options", b"DENY"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                for name, value in secure:
                    if name not in names:
                        headers.append((name, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, add_headers)


async def _send_json(send: Any, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"content-security-policy", b"default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"),
            (b"x-frame-options", b"DENY"),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


def _actor_public(actor: Any) -> dict[str, Any]:
    fields = ("participant_id", "name", "kind", "writable", "board_id", "workflow_version", "scopes")
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(actor, field, None)
        if isinstance(value, (str, bool, int, float)) or (
            field == "scopes" and isinstance(value, (tuple, list, set, frozenset))
        ):
            result[field] = list(value) if field == "scopes" else value
    return result


def _is_board_error(exc: Exception) -> bool:
    return hasattr(exc, "code") and hasattr(exc, "message") and isinstance(getattr(exc, "status", None), int)


def _redact_details(value: Any, token: str | None) -> Any:
    if not token:
        return value
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact_details(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact_details(key, token): _redact_details(item, token) for key, item in value.items()}
    return value


def _error_payload(exc: Exception, *, token: str | None = None) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, RequestError):
        return exc.status, {"error": {"code": exc.code, "message": exc.message}}
    if _is_board_error(exc):
        code = getattr(exc, "code")
        message = getattr(exc, "message")
        status = getattr(exc, "status")
        if not isinstance(code, str) or not code.replace("_", "").isalnum():
            code = "board_error"
        if not isinstance(message, str):
            message = "The board request could not be completed."
        if token:
            message = message.replace(token, "[redacted]")
        error: dict[str, Any] = {"code": code, "message": message}
        details = getattr(exc, "details", None)
        if isinstance(details, dict) and details:
            error["details"] = _redact_details(details, token)
        return status if 400 <= status <= 599 else 500, {"error": error}
    return 500, {"error": {"code": "internal_error", "message": "The board request could not be completed."}}


def create_app(root: Path, *, port: int, service: Any | None = None, should_stop: Callable[[], bool] | None = None) -> Any:
    """Create the local ASGI app for one workspace and one BoardService.

    Bind the returned app to ``127.0.0.1`` on the same ``port`` passed here.
    ``port`` must be the actual listening port; it is part of Host and Origin
    validation and the SDK's DNS-rebinding allow list. ``should_stop`` reports
    that the server is shutting down: open event streams end at once instead of
    holding the process until the browser hangs up.
    """

    try:
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
        from starlette.routing import Mount, Route
        from mcp.server.transport_security import TransportSecuritySettings
    except ImportError as exc:  # pragma: no cover - depends on install profile
        raise RuntimeError("The optional board transport requires Starlette and mcp==2.2.0.") from exc

    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    supplied_workspace = Path(root).expanduser().absolute()
    if service is None:
        from prism_cli.board_service import BoardService

        # BoardService must see the original path components so it can reject
        # a symlink/junction root before resolving it.
        service = BoardService(supplied_workspace)
    workspace = Path(getattr(service, "root", supplied_workspace)).resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("root must be a directory")
    validate_graph_inputs = getattr(service, "validate_graph_inputs", None)
    if not callable(validate_graph_inputs):
        raise TypeError("BoardService must expose validate_graph_inputs() before graph reads.")
    cookie_tag = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:16]
    cookie_name = f"prism_board_{cookie_tag}_session"
    sessions: dict[str, _Session] = {}
    sessions_lock = threading.RLock()
    graph = _LiveGraph(workspace, validate_graph_inputs)

    from prism_cli.board_mcp import create_mcp_server

    board_api = _SnapshotRefreshingService(service, graph)
    mcp_server = create_mcp_server(board_api)
    allowed_hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    if port == 80:
        allowed_hosts.extend(("127.0.0.1", "localhost"))
    allowed_origins = [f"http://{host}" for host in allowed_hosts]
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        host="127.0.0.1",
        max_request_body_size=MAX_REQUEST_BYTES,
        transport_security=TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )

    def cookie_value(request: Request) -> str | None:
        values = request.headers.getlist("cookie")
        if len(values) > 1:
            raise RequestError(400, "invalid_cookie", "The request is malformed.")
        if not values:
            return None
        found: list[str] = []
        for item in values[0].split(";"):
            key, separator, value = item.strip().partition("=")
            if separator and key == cookie_name:
                found.append(value)
        if len(found) > 1:
            raise RequestError(400, "ambiguous_credentials", "Use one board session at a time.")
        return found[0] if found else None

    def bearer_value(request: Request) -> str | None:
        values = request.headers.getlist("authorization")
        if len(values) > 1:
            raise RequestError(400, "ambiguous_credentials", "Use one credential at a time.")
        if not values:
            return None
        scheme, separator, token = values[0].partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or token.strip() != token or " " in token:
            raise RequestError(401, "unauthorized", "A valid Prism Bearer token is required.")
        return token

    async def authenticate(token: str) -> Any:
        try:
            return await asyncio.to_thread(service.authenticate, token)
        except Exception:
            raise RequestError(401, "unauthorized", "The Prism participant token is invalid or revoked.") from None

    def expire_cookie(response: Any) -> Any:
        response.delete_cookie(cookie_name, path="/", httponly=True, samesite="strict")
        return response

    def set_cookie(response: Any, session_id: str, request: Request) -> Any:
        response.set_cookie(
            cookie_name,
            session_id,
            max_age=SESSION_TTL_SECONDS,
            path="/",
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
        )
        return response

    async def actor_for(request: Request, *, mutation: bool = False) -> tuple[Any, str, _Session | None, str | None]:
        token = bearer_value(request)
        session_id = cookie_value(request)
        if token and session_id:
            raise RequestError(400, "ambiguous_credentials", "Use either a Bearer token or a board session.")
        origin = request.headers.get("origin")
        if mutation:
            if token:
                if origin is not None:
                    raise RequestError(403, "csrf_required", "Browser writes require an authenticated same-origin session.")
            else:
                _require_origin(request)
        if token:
            actor = await authenticate(token)
            return actor, token, None, None
        if not session_id:
            raise RequestError(401, "unauthorized", "A Prism board session or Bearer token is required.")
        with sessions_lock:
            current = sessions.get(session_id)
        if current is None or current.expires_at <= time.time():
            with sessions_lock:
                sessions.pop(session_id, None)
            raise RequestError(401, "session_expired", "The Prism board session has expired.")
        actor = await authenticate(current.token)
        identity = (
            getattr(actor, "participant_id", None),
            getattr(actor, "board_id", None),
            getattr(actor, "workflow_version", None),
            getattr(actor, "kind", None),
        )
        expected = (current.participant_id, current.board_id, current.workflow_version, current.kind)
        if identity != expected or getattr(actor, "kind", None) != "human":
            with sessions_lock:
                sessions.pop(session_id, None)
            raise RequestError(401, "session_invalidated", "The board grant or workflow contract changed. Sign in again.")
        if mutation:
            _require_origin(request)
            supplied = request.headers.get("x-prism-csrf", "")
            if not supplied or not hmac.compare_digest(supplied, current.csrf):
                raise RequestError(403, "csrf_failed", "The same-origin request could not be verified.")
        return actor, current.token, current, session_id

    def _require_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '').lower()}"
        if not origin or origin != expected:
            raise RequestError(403, "same_origin_required", "This action requires the local same-origin Prism board.")

    async def json_body(request: Request) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise RequestError(415, "json_required", "Send this request as application/json.")
        try:
            value = json.loads(await request.body())
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RequestError(400, "invalid_json", "The JSON request body is invalid.") from None
        if not isinstance(value, dict):
            raise RequestError(400, "invalid_json", "The request body must be a JSON object.")
        return value

    async def invoke(request: Request, method: str, *args: Any, mutation: bool = False, **kwargs: Any) -> Any:
        token: str | None = None
        try:
            actor, token, _session, _session_id = await actor_for(request, mutation=mutation)
            result = await asyncio.to_thread(getattr(board_api, method), actor, *args, **kwargs)
            if not isinstance(result, dict):
                raise RuntimeError("invalid BoardService response")
            return JSONResponse(result)
        except Exception as exc:
            status, payload = _error_payload(exc, token=token)
            response = JSONResponse(payload, status_code=status)
            if status == 401 and request.url.path.startswith(API_PREFIX):
                expire_cookie(response)
            return response

    async def request_error_handler(_request: Request, exc: Exception) -> Any:
        status, payload = _error_payload(exc)
        return JSONResponse(payload, status_code=status)

    async def login_page(_request: Request) -> Any:
        nonce = secrets.token_urlsafe(18)
        script = """const form=document.querySelector('form');const status=document.querySelector('[role=status]');form.addEventListener('submit',async(e)=>{e.preventDefault();const field=form.elements.token;const token=field.value;field.value='';status.textContent='Connecting…';try{const response=await fetch('/api/board/v1/auth/exchange',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});const data=await response.json();if(!response.ok){status.textContent=data.error?.message||'Connection failed.';return}location.replace('/')}catch{status.textContent='Connection failed.'}});"""
        html = (
            "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Connect to Prism</title><main><h1>Connect to your Prism board</h1>"
            "<p>Enter a human participant token created for this workspace.</p>"
            "<form><label>Participant token <input name=\"token\" type=\"password\" autocomplete=\"off\" required></label>"
            "<button type=\"submit\">Connect</button></form><p role=\"status\" aria-live=\"polite\"></p></main>"
            f"<script nonce=\"{nonce}\">{script}</script></html>"
        )
        response = HTMLResponse(html)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            f"form-action 'self'; script-src 'nonce-{nonce}'"
        )
        return response

    async def home(request: Request) -> Any:
        try:
            await actor_for(request)
        except RequestError as exc:
            if exc.status != 401:
                status, payload = _error_payload(exc)
                return JSONResponse(payload, status_code=status)
            response = await login_page(request)
            if cookie_name in request.headers.get("cookie", ""):
                expire_cookie(response)
            return response
        except Exception:
            return JSONResponse({"error": {"code": "internal_error", "message": "The board request could not be completed."}}, status_code=500)
        from prism_cli.wiki_graph_html import render_html

        try:
            _epoch, _version, envelope = graph.snapshot()
        except GraphUnavailable:
            return JSONResponse({"error": {"code": "graph_unavailable", "message": "Workspace graph inputs are temporarily unavailable."}}, status_code=503)
        nonce = secrets.token_urlsafe(18)
        html = render_html(envelope, mode="live")
        html = re.sub(r"<script(?=\s|>)", f'<script nonce="{nonce}"', html, flags=re.IGNORECASE)
        response = HTMLResponse(html)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            f"script-src 'nonce-{nonce}'"
        )
        return response

    async def data_json(request: Request) -> Any:
        try:
            await actor_for(request)
        except Exception as exc:
            status, payload = _error_payload(exc)
            response = JSONResponse(payload, status_code=status)
            if status == 401:
                expire_cookie(response)
            return response
        try:
            epoch, version, envelope = graph.snapshot()
        except GraphUnavailable:
            return JSONResponse({"error": {"code": "graph_unavailable", "message": "Workspace graph inputs are temporarily unavailable."}}, status_code=503)
        return JSONResponse({"epoch": epoch, "version": version, "envelope": envelope})

    async def events(request: Request) -> Any:
        try:
            _actor, token, session, session_id = await actor_for(request)
        except Exception as exc:
            status, payload = _error_payload(exc)
            response = JSONResponse(payload, status_code=status)
            if status == 401:
                expire_cookie(response)
            return response
        try:
            graph.snapshot()
        except GraphUnavailable:
            return JSONResponse({"error": {"code": "graph_unavailable", "message": "Workspace graph inputs are temporarily unavailable."}}, status_code=503)

        def stopping() -> bool:
            return should_stop is not None and bool(should_stop())

        async def pause(seconds: float) -> None:
            deadline = time.monotonic() + seconds
            while not stopping():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                await asyncio.sleep(min(STREAM_STOP_CHECK_SECONDS, remaining))

        async def event_stream() -> Any:
            last_version = -1
            last_check = time.monotonic()
            while not stopping() and not await request.is_disconnected():
                if time.monotonic() - last_check >= SESSION_RECHECK_SECONDS:
                    try:
                        # Do not use a fabricated actor; resolve the same token
                        # and current board binding before continuing the stream.
                        if session_id:
                            current_id = cookie_value(request)
                            if current_id != session_id:
                                return
                            await actor_for(request)
                        else:
                            await authenticate(token)
                    except Exception:
                        return
                    last_check = time.monotonic()
                try:
                    epoch, version, _envelope = graph.snapshot()
                except GraphUnavailable:
                    return
                if version != last_version:
                    last_version = version
                    yield f"id: {epoch}:{version}\ndata: {version}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await pause(GRAPH_POLL_SECONDS)

        response = StreamingResponse(event_stream(), media_type="text/event-stream")
        return response

    def scavenge_sessions() -> None:
        """Drop expired sessions. Every session has the same lifetime and is
        inserted in order, so the oldest come first and the scan stops at the
        first live one: the work is proportional to the expired count."""
        now = time.time()
        with sessions_lock:
            for session_id, session in list(itertools.takewhile(lambda item: item[1].expires_at <= now, sessions.items())):
                del sessions[session_id]

    async def exchange(request: Request) -> Any:
        token: str | None = None
        try:
            _require_origin(request)
            scavenge_sessions()
            if bearer_value(request) is not None or cookie_value(request) is not None:
                raise RequestError(400, "ambiguous_credentials", "Sign out before exchanging another participant token.")
            payload = await json_body(request)
            if set(payload) != {"token"}:
                raise RequestError(400, "invalid_exchange", "The token exchange accepts only one token field.")
            token = payload.get("token")
            if not isinstance(token, str) or not token or token.strip() != token or len(token) > 4096:
                raise RequestError(400, "invalid_token", "Provide one valid participant token.")
            actor = await authenticate(token)
            if getattr(actor, "kind", None) != "human":
                raise RequestError(403, "human_grant_required", "Browser sessions require a human participant grant.")
            session_id = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            session = _Session(
                token=token,
                csrf=csrf,
                participant_id=getattr(actor, "participant_id", None),
                board_id=getattr(actor, "board_id", None),
                workflow_version=getattr(actor, "workflow_version", None),
                kind="human",
                expires_at=time.time() + SESSION_TTL_SECONDS,
            )
            with sessions_lock:
                sessions[session_id] = session
            response = JSONResponse({"actor": _actor_public(actor), "csrf_token": csrf})
            return set_cookie(response, session_id, request)
        except Exception as exc:
            status, result = _error_payload(exc, token=token)
            return JSONResponse(result, status_code=status)

    async def session_info(request: Request) -> Any:
        try:
            _actor, _token, session, _session_id = await actor_for(request)
            if session is None:
                raise RequestError(401, "browser_session_required", "This endpoint requires a browser board session.")
            return JSONResponse({"actor": _actor_public(_actor), "csrf_token": session.csrf})
        except Exception as exc:
            status, payload = _error_payload(exc)
            response = JSONResponse(payload, status_code=status)
            if status == 401:
                expire_cookie(response)
            return response

    async def logout(request: Request) -> Any:
        try:
            _require_origin(request)
            session_id = cookie_value(request)
            if session_id:
                with sessions_lock:
                    session = sessions.get(session_id)
                if session is not None:
                    supplied = request.headers.get("x-prism-csrf", "")
                    if not supplied or not hmac.compare_digest(supplied, session.csrf):
                        raise RequestError(403, "csrf_failed", "The same-origin request could not be verified.")
                with sessions_lock:
                    sessions.pop(session_id, None)
            response = Response(status_code=204)
            return expire_cookie(response)
        except Exception as exc:
            status, payload = _error_payload(exc)
            return JSONResponse(payload, status_code=status)

    async def read_workspace(request: Request) -> Any:
        payload = await json_body(request)
        paths = payload.get("paths")
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            return JSONResponse({"error": {"code": "invalid_paths", "message": "paths must be a list of relative path strings."}}, status_code=400)
        cursor = payload.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            return JSONResponse({"error": {"code": "invalid_paths", "message": "cursor must be a string or null."}}, status_code=400)
        return await invoke(request, "read_workspace", paths, cursor, mutation=True)

    async def list_workspace(request: Request) -> Any:
        payload = await json_body(request)
        if set(payload) - {"prefix", "cursor"}:
            return JSONResponse({"error": {"code": "invalid_listing", "message": "Only prefix and cursor are accepted."}}, status_code=400)
        prefix = payload.get("prefix", "knowledge")
        cursor = payload.get("cursor")
        if not isinstance(prefix, str) or (cursor is not None and not isinstance(cursor, str)):
            return JSONResponse({"error": {"code": "invalid_listing", "message": "prefix must be a string and cursor must be a string or null."}}, status_code=400)
        return await invoke(request, "list_workspace", prefix, cursor, mutation=True)

    async def query(request: Request) -> Any:
        payload = await json_body(request)
        if set(payload) - {"kind", "value", "action", "cursor"}:
            return JSONResponse({"error": {"code": "invalid_query", "message": "Only kind, value, action, and cursor are accepted."}}, status_code=400)
        kind = payload.get("kind")
        value = payload.get("value")
        action = payload.get("action")
        cursor = payload.get("cursor")
        allowed_kinds = {"show", "blockers", "owner", "app", "search", "transition-preflight", "lint"}
        if (
            not isinstance(kind, str)
            or kind not in allowed_kinds
            or (value is not None and not isinstance(value, str))
            or (action is not None and not isinstance(action, str))
            or (cursor is not None and not isinstance(cursor, str))
        ):
            return JSONResponse({"error": {"code": "invalid_query", "message": "kind must be an approved query; value, action and cursor must be strings when supplied."}}, status_code=400)
        return await invoke(request, "query", kind, value, action, cursor, mutation=True)

    async def preview_transition(request: Request) -> Any:
        payload = await json_body(request)
        feature_id, action = payload.get("feature_id"), payload.get("action")
        inputs = payload.get("inputs")
        if not isinstance(feature_id, str) or not isinstance(action, str) or (inputs is not None and not isinstance(inputs, dict)):
            return JSONResponse({"error": {"code": "invalid_preview", "message": "feature_id and action must be strings; inputs must be an object."}}, status_code=400)
        return await invoke(request, "preview_transition", feature_id, action, inputs, mutation=True)

    async def preview_skill(request: Request) -> Any:
        payload = await json_body(request)
        skill = payload.get("skill")
        changes = payload.get("changes")
        moves = payload.get("moves")
        revisions = payload.get("read_revisions")
        if (
            not isinstance(skill, str)
            or not isinstance(changes, list)
            or (moves is not None and not isinstance(moves, list))
            or (revisions is not None and not isinstance(revisions, dict))
        ):
            return JSONResponse({"error": {"code": "invalid_preview", "message": "skill and changes are required; moves and read_revisions must be arrays and an object."}}, status_code=400)
        return await invoke(request, "preview_skill", skill, changes, moves, revisions, mutation=True)

    async def apply(request: Request) -> Any:
        payload = await json_body(request)
        preview_id, operation_id = payload.get("preview_id"), payload.get("operation_id")
        if not isinstance(preview_id, str) or not isinstance(operation_id, str):
            return JSONResponse({"error": {"code": "invalid_operation", "message": "preview_id and operation_id are required strings."}}, status_code=400)
        return await invoke(request, "apply", preview_id, operation_id, mutation=True)

    async def recover(request: Request) -> Any:
        body = await request.body()
        payload = await json_body(request) if body else {}
        if set(payload) - {"review_revision", "semantic_review_acknowledged", "abandon"}:
            return JSONResponse(
                {"error": {"code": "invalid_recovery", "message": "Only review_revision, semantic_review_acknowledged and abandon are accepted."}},
                status_code=400,
            )
        review_revision = payload.get("review_revision")
        semantic_review_acknowledged = payload.get("semantic_review_acknowledged", False)
        abandon = payload.get("abandon", False)
        if (
            (review_revision is not None and not isinstance(review_revision, str))
            or not isinstance(semantic_review_acknowledged, bool)
            or not isinstance(abandon, bool)
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "invalid_recovery",
                        "message": "review_revision must be a string or null, and semantic_review_acknowledged and abandon must be booleans.",
                    }
                },
                status_code=400,
            )
        return await invoke(
            request,
            "recover",
            request.path_params["operation_id"],
            review_revision,
            semantic_review_acknowledged,
            mutation=True,
            **({"abandon": True} if abandon else {}),
        )

    async def discover(request: Request) -> Any:
        return await invoke(request, "discover")

    async def list_skills(request: Request) -> Any:
        return await invoke(request, "list_skills")

    async def get_skill(request: Request) -> Any:
        return await invoke(request, "get_skill", request.path_params["name"])

    async def operation(request: Request) -> Any:
        return await invoke(request, "operation", request.path_params["operation_id"])

    async def changes(request: Request) -> Any:
        cursor = request.query_params.get("cursor")
        return await invoke(request, "changes", cursor)

    routes = [
        Route("/", home, methods=["GET"]),
        Route("/index.html", home, methods=["GET"]),
        Route("/data.json", data_json, methods=["GET"]),
        Route("/events", events, methods=["GET"]),
        Route(f"{API_PREFIX}/auth/exchange", exchange, methods=["POST"]),
        Route(f"{API_PREFIX}/auth/session", session_info, methods=["GET"]),
        Route(f"{API_PREFIX}/auth/logout", logout, methods=["POST"]),
        Route(f"{API_PREFIX}/discover", discover, methods=["GET"]),
        Route(f"{API_PREFIX}/workspace/read", read_workspace, methods=["POST"]),
        Route(f"{API_PREFIX}/workspace/list", list_workspace, methods=["POST"]),
        Route(f"{API_PREFIX}/query", query, methods=["POST"]),
        Route(f"{API_PREFIX}/skills", list_skills, methods=["GET"]),
        Route(f"{API_PREFIX}/skills/{{name:str}}", get_skill, methods=["GET"]),
        Route(f"{API_PREFIX}/previews/transition", preview_transition, methods=["POST"]),
        Route(f"{API_PREFIX}/previews/skill", preview_skill, methods=["POST"]),
        Route(f"{API_PREFIX}/apply", apply, methods=["POST"]),
        Route(f"{API_PREFIX}/operations/{{operation_id:str}}/recover", recover, methods=["POST"]),
        Route(f"{API_PREFIX}/operations/{{operation_id:str}}", operation, methods=["GET"]),
        Route(f"{API_PREFIX}/changes", changes, methods=["GET"]),
        Mount("/", app=mcp_app),
    ]

    @asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        started = False
        try:
            start = getattr(service, "start", None)
            if callable(start):
                await asyncio.to_thread(start)
                started = True
            graph.start()
            async with mcp_server.session_manager.run():
                yield
        finally:
            graph.close()
            close = getattr(service, "close", None)
            if started and callable(close):
                await asyncio.to_thread(close)

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={RequestError: request_error_handler},
    )
    app.add_middleware(_BoundaryMiddleware, port=port, cookie_name=cookie_name, max_bytes=MAX_REQUEST_BYTES)
    app.add_middleware(_SecurityHeadersMiddleware)
    app.state.board_service = service
    app.state.board_root = workspace
    app.state.board_sessions = sessions
    app.state.board_cookie_name = cookie_name
    app.state.board_graph = graph
    app.state.mcp_server = mcp_server
    return app


create_board_app = create_app


def loopback_port_problem(port: int) -> str | None:
    """Return why ``port`` cannot be bound on loopback, or ``None`` when it is free.

    The probe binds and releases immediately. POSIX listeners set
    ``SO_REUSEADDR`` as Uvicorn does, so a socket in TIME_WAIT is not reported
    as busy; Windows must not set it, because there it allows binding over an
    active listener.
    """

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            return "it is already in use"
        return str(exc.strerror or exc).strip() or "it cannot be bound"
    except OverflowError:
        return "it is not a valid port"
    finally:
        probe.close()
    return None


def _grant_command_hint(root: Path) -> str:
    try:
        path = "." if root.samefile(Path.cwd()) else str(root)
    except OSError:
        path = str(root)
    if " " in path:
        path = f'"{path}"'
    return f'prism board grant "NAME" --kind human|agent [--write] --path {path}'


def quiet_connection_reset_handler() -> Callable[[Any, dict[str, Any]], None]:
    """An asyncio exception handler that reports a client's reset connection once.

    A client that closes its connection abruptly makes the Windows event loop
    log a `ConnectionResetError` traceback. That case alone is reduced to one
    quiet line for the whole run; every other exception keeps the loop's
    default reporting.
    """

    reported = False

    def handle(loop: Any, context: dict[str, Any]) -> None:
        nonlocal reported
        if isinstance(context.get("exception"), ConnectionResetError):
            if not reported:
                reported = True
                print("A client closed its connection abruptly (connection reset); this is harmless and is not logged again.", file=sys.stderr, flush=True)
            return
        loop.default_exception_handler(context)

    return handle


def serve_board(root: Path, port: int = DEFAULT_BOARD_PORT, open_browser: bool = True) -> int:
    """Run the local board app on loopback using Uvicorn."""

    try:
        import uvicorn
        from prism_cli.board_service import BoardError, BoardService
    except ImportError as exc:  # pragma: no cover - depends on install profile
        print("The board server requires the optional uvicorn transport dependency.", file=sys.stderr)
        return 4
    # Fail before any workspace state is touched or a URL is printed.
    port_problem = loopback_port_problem(port)
    if port_problem is not None:
        print(f"Cannot start the Prism board on port {port}: {port_problem}. Choose another with --port.", file=sys.stderr)
        return 4
    service: Any | None = None
    running: list[Any] = []
    try:
        supplied_workspace = Path(root).expanduser().absolute()
        service = BoardService(supplied_workspace)
        service.start()
        # An interrupt sets the server's exit flag; open event streams watch it so a connected browser cannot hold the process.
        app = create_app(
            supplied_workspace,
            port=port,
            service=service,
            should_stop=lambda: bool(running) and bool(running[0].should_exit),
        )
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
            server_header=False,
            date_header=False,
            timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS,
        )

        class _BoardServer(uvicorn.Server):
            async def serve(self, sockets: Any = None) -> None:
                asyncio.get_running_loop().set_exception_handler(quiet_connection_reset_handler())
                await super().serve(sockets=sockets)

        server = _BoardServer(config)
        running.append(server)
    except BoardError as exc:
        if service is not None:
            service.close()
        print(f"Cannot start the Prism board: {exc.message}", file=sys.stderr)
        return 4
    except (OSError, ValueError, RuntimeError) as exc:
        if service is not None:
            service.close()
        print(f"Cannot start the Prism board on port {port}: {exc}", file=sys.stderr)
        return 4

    url = f"http://127.0.0.1:{port}/"
    # Flushed so a pipe or log file shows the banner while the server runs.
    print(f"Prism board: {url}", flush=True)
    print(f"MCP endpoint: http://127.0.0.1:{port}/mcp", flush=True)
    print(f"Issue a participant grant (the token is printed once): {_grant_command_hint(supplied_workspace)}", flush=True)
    print("Local only. Press Ctrl+C to stop.", flush=True)

    opener: threading.Thread | None = None
    if open_browser:
        def open_when_ready() -> None:
            deadline = time.monotonic() + 20
            while not server.started and not server.should_exit and time.monotonic() < deadline:
                time.sleep(0.05)
            if server.started:
                try:
                    import webbrowser

                    webbrowser.open(url)
                except Exception:
                    pass

        opener = threading.Thread(target=open_when_ready, name="prism-board-browser", daemon=True)
        opener.start()
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nStopped.")
    except OSError as exc:
        print(f"Cannot start the Prism board on port {port}.", file=sys.stderr)
        return 4
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        print(f"Cannot start the Prism board on port {port}.", file=sys.stderr)
        return 4
    finally:
        if opener is not None:
            opener.join(timeout=0.2)
        if service is not None:
            service.close()
    if not server.started:
        print("Cannot start the Prism board; the server did not finish startup.", file=sys.stderr)
        return 4
    return 0
