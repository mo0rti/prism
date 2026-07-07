"""Read-only local server for the live wiki-graph dashboard.

Stdlib only. The server never writes to the workspace; it re-parses the wiki
when file mtimes change and notifies the browser over Server-Sent Events.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prism_cli.wiki_graph import build_graph
from prism_cli.wiki_graph_html import render_html


POLL_SECONDS = 1.5
WATCH_DIRS = ("knowledge",)


def _workspace_fingerprint(root: Path) -> tuple[int, int]:
    latest = 0
    count = 0
    for directory in WATCH_DIRS:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            try:
                stat = path.stat()
            except OSError:
                continue
            count += 1
            latest = max(latest, stat.st_mtime_ns)
    return latest, count


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
            self.fingerprint = fingerprint
            self.envelope = build_graph(self.root)
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
                _version, envelope = state.snapshot()
                html = render_html(envelope, mode="live")
                self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
                return
            if self.path == "/data.json":
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
    print("Live updates: watching knowledge/ for changes. Read-only; press Ctrl+C to stop.")
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
