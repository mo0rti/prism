"""Read-only local server for the live wiki-graph dashboard.

Stdlib only. The server never writes to the workspace; it re-parses the wiki
when relevant workspace content changes and notifies the browser over
Server-Sent Events.
"""

from __future__ import annotations

import hashlib
import json
import stat
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prism_cli.status import IGNORED_INTAKE_FILES
from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_graph_html import render_html
from prism_cli.workspace import COPIER_ANSWERS_FILE, MANIFEST_FILE, PLATFORM_DIRS


POLL_SECONDS = 1.5
WATCH_WIKI_DIR = "knowledge/wiki"
WATCH_QUEUE_DIRS = ("knowledge/intake/pending", "knowledge/intake/quarantined")
WATCH_FILES = (MANIFEST_FILE, COPIER_ANSWERS_FILE)


def _file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return "unreadable"
    return digest.hexdigest()


def _path_kind(path: Path) -> str:
    try:
        path_stat = path.stat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if stat.S_ISDIR(path_stat.st_mode):
        return "directory"
    if stat.S_ISREG(path_stat.st_mode):
        return "file"
    return f"mode:{path_stat.st_mode}"


def _workspace_fingerprint(root: Path) -> tuple[tuple[str, str], ...]:
    """Return fingerprints for graph inputs and workspace-derived diagnostics."""
    entries: list[tuple[str, str]] = []
    entries.append(("today", date.today().isoformat()))

    for relative in WATCH_FILES:
        path = root / relative
        file_kind = _path_kind(path)
        if file_kind == "file":
            entries.append((relative, _file_fingerprint(path)))
        else:
            entries.append((relative, file_kind))

    wiki_root = root / WATCH_WIKI_DIR
    wiki_kind = _path_kind(wiki_root)
    entries.append((WATCH_WIKI_DIR, wiki_kind))
    if wiki_kind == "directory":
        try:
            paths = sorted(wiki_root.rglob("*.md"), key=lambda path: path.as_posix())
        except OSError:
            paths = []
            entries.append((WATCH_WIKI_DIR, "unreadable"))
        for path in paths:
            try:
                path_stat = path.stat()
                relative = path.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if stat.S_ISREG(path_stat.st_mode):
                entries.append((relative, _file_fingerprint(path)))
            else:
                entries.append((relative, f"mode:{path_stat.st_mode}"))

    for queue_relative in WATCH_QUEUE_DIRS:
        queue_root = root / queue_relative
        queue_kind = _path_kind(queue_root)
        entries.append((queue_relative, queue_kind))
        if queue_kind != "directory":
            continue
        try:
            children = sorted(queue_root.iterdir(), key=lambda path: path.name)
        except OSError:
            entries.append((queue_relative, "unreadable"))
            continue
        for child in children:
            if child.name in IGNORED_INTAKE_FILES or child.name.startswith("_") or child.name.startswith("."):
                continue
            try:
                relative = child.relative_to(root).as_posix()
            except ValueError:
                continue
            entries.append((relative, _path_kind(child)))

    for platform_id, relative in sorted(PLATFORM_DIRS.items()):
        entries.append((f"platform:{platform_id}", _path_kind(root / relative)))
    return tuple(entries)


class _GraphState:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = threading.Lock()
        self.version = 1
        self.fingerprint = _workspace_fingerprint(root)
        self.envelope = build_graph(root)

    def refresh_if_changed(self) -> bool:
        fingerprint = _workspace_fingerprint(self.root)
        with self.lock:
            if fingerprint == self.fingerprint:
                return False
            envelope = build_graph(self.root)
            self.envelope = envelope
            self.fingerprint = fingerprint
            self.version += 1
            return True

    def snapshot(self) -> tuple[int, dict]:
        with self.lock:
            return self.version, self.envelope


def _make_handler(state: _GraphState) -> type[BaseHTTPRequestHandler]:
    class GraphHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # keep the terminal quiet
            pass

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self.path in ("/", "/index.html"):
                state.refresh_if_changed()
                _version, envelope = state.snapshot()
                html = render_html(envelope, mode="live")
                self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
                return
            if self.path == "/data.json":
                state.refresh_if_changed()
                version, envelope = state.snapshot()
                payload = json.dumps({"version": version, "envelope": envelope})
                self._send(200, "application/json; charset=utf-8", payload.encode("utf-8"))
                return
            if self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                last_sent = 0
                try:
                    while True:
                        state.refresh_if_changed()
                        version, _envelope = state.snapshot()
                        if version != last_sent:
                            last_sent = version
                            self.wfile.write(f"data: {version}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        else:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                        time.sleep(POLL_SECONDS)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    return
            self._send(404, "text/plain; charset=utf-8", b"not found")

    return GraphHandler


def serve_graph(root: Path, port: int) -> int:
    state = _GraphState(root.expanduser().resolve())
    server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(state))
    url = f"http://127.0.0.1:{port}/"
    print(f"Prism graph dashboard: {url}")
    print("Live updates: watching graph wiki, intake queues, manifest, answers, and platform directories. Read-only; press Ctrl+C to stop.")
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:  # pragma: no cover - opening a browser is best-effort
        pass
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0
