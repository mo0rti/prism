#!/usr/bin/env python
"""Measure how the Prism board behaves as a workspace grows.

For each requested size the script builds a deterministic, product-neutral
workspace of synthetic feature pages in a temporary folder under ``--out``,
then measures the real BoardService, HTTP app and MCP tools against disposable
copies of it:

* cold start: BoardService + create_app + server start up to the first
  successful ``/data.json`` response;
* ``/data.json`` latency (p50 / p95) over a real loopback socket served by
  uvicorn in a thread;
* the shared change-detection scan (``_LiveGraph._poll``): time per scan and
  process CPU time with 0, 1 and 5 concurrent viewers for a fixed window, for
  two viewer behaviours (a held ``/events`` stream, and ``/data.json`` polling);
* MCP tool latency through the real SDK client over the ASGI transport:
  ``discover``, ``query`` (blockers), ``get_skill`` (po-intake),
  ``preview_transition`` (po-handoff on a ready feature) and ``apply`` of that
  preview on a fresh disposable copy for every repetition;
* peak process memory (one worker process per size).

Nothing outside ``--out`` is written and the product code is only read. Run it
with the interpreter that has Prism's board transport dependencies installed::

    python scripts/measure-board-scale.py --out <dir> [--sizes 10,100,500,1000] [--samples 50]

Each size runs in its own worker process so the peak-memory figure belongs to
that size alone. The client threads that generate load share the process (and
the GIL) with the server thread, so CPU figures include the measuring client;
the idle row (0 viewers) is the baseline to compare against.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import http.client
import json
import logging
import math
import os
import platform
import random
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SIZES = (10, 100, 500, 1000)
SEED = 20261004
WARMUP_REQUESTS = 5
VIEWER_WINDOW_SECONDS = 10.0
VIEWER_COUNTS = (1, 5)
POLL_INTERVAL_SECONDS = 1.5  # matches GRAPH_POLL_SECONDS, the browser refresh cadence
PROCESSED_SOURCE = "knowledge/intake/processed/document-review-brief/brief.md"
READY_FEATURE = "F-001"
MCP_ORIGIN_PORT = 8765  # ASGI transport only; the port feeds Host/Origin validation


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile of a non-empty list."""

    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100.0
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def stats_ms(seconds: list[float]) -> dict[str, Any]:
    """Summarise a list of durations given in seconds as milliseconds."""

    if not seconds:
        return {"n": 0}
    millis = [value * 1000.0 for value in seconds]
    return {
        "n": len(millis),
        "p50": round(percentile(millis, 50), 3),
        "p95": round(percentile(millis, 95), 3),
        "max": round(max(millis), 3),
        "mean": round(statistics.fmean(millis), 3),
    }


def compact_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _windows_memory_counters() -> tuple[int, int] | None:
    """(peak working set, working set) of this process in bytes, via the Windows API."""

    class _Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint32),
            ("PageFaultCount", ctypes.c_uint32),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters), ctypes.c_uint32]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize), int(counters.WorkingSetSize)
    except Exception:
        pass
    return None


def peak_rss_bytes() -> int | None:
    """Peak resident memory of this process. psutil only if already installed."""

    if sys.platform == "win32":
        try:
            import psutil  # type: ignore

            peak = getattr(psutil.Process().memory_info(), "peak_wset", None)
            if peak:
                return int(peak)
        except Exception:
            pass
        counters = _windows_memory_counters()
        return None if counters is None else counters[0]
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak) if sys.platform == "darwin" else int(peak) * 1024
    except Exception:
        return None


def current_rss_bytes() -> int | None:
    if sys.platform == "win32":
        try:
            import psutil  # type: ignore

            return int(psutil.Process().memory_info().rss)
        except Exception:
            pass
        counters = _windows_memory_counters()
        return None if counters is None else counters[1]
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        return None


def _mib(value: int | None) -> float | None:
    return None if value is None else round(value / (1024 * 1024), 1)


# --------------------------------------------------------------------------
# Machine and build information
# --------------------------------------------------------------------------


def _cpu_model() -> str:
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        if sys.platform == "darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=10).stdout.strip() or platform.processor()
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "unknown"


def _total_ram_bytes() -> int | None:
    try:
        if sys.platform == "win32":

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("sullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
            return None
        if sys.platform == "darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10).stdout.strip())
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return None


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _prism_version() -> str:
    try:
        from importlib.metadata import version

        return version("prism-kit")
    except Exception:
        pass
    try:
        match = re.search(r'^version\s*=\s*"([^"]+)"', (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass
    return "unknown"


def machine_info() -> dict[str, Any]:
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    if commit is None:
        git_text = "unknown (not a git checkout or git unavailable)"
    else:
        git_text = commit + (" plus uncommitted changes" if status else "")
    ram = _total_ram_bytes()
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu_model": _cpu_model(),
        "cpu_cores_logical": os.cpu_count(),
        "ram_gib": None if ram is None else round(ram / 1024**3, 1),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "prism_version": _prism_version(),
        "git_commit": git_text,
        "uncommitted_paths": len(status.splitlines()) if status else 0,
    }


# --------------------------------------------------------------------------
# Deterministic workspace construction
# --------------------------------------------------------------------------

_SUBJECTS = ("Document review", "Review summary", "Reviewer assignment", "Outcome log", "Follow-up request", "Review checklist", "Approval record", "Review digest")
_QUESTIONS = (
    "Which points should a review summary highlight?",
    "How long is a recorded outcome kept?",
    "Who may reopen a closed review?",
    "What is the fallback when a reviewer is unavailable?",
    "Should follow-up requests expire?",
)
_ANSWER = "resolved: Capture key points and requested follow-up."


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def feature_plan(number: int) -> dict[str, Any]:
    """Return the fixed status and open-question shape for one feature number.

    Pattern per ten features: raw with open questions, raw without, ready PO
    handoffs (specified, answered), and a blocked handoff (specified with an
    open PO question). F-001 is always a ready handoff.
    """

    if number == 1:
        return {"status": "specified", "owner": "po", "questions": [("po", False)]}
    slot = (number - 1) % 10
    if slot in (0, 1, 2, 3):
        return {"status": "raw", "owner": "po", "questions": [("po", True)] * (1 + slot % 2)}
    if slot == 4:
        return {"status": "raw", "owner": "po", "questions": [("po", False)]}
    if slot in (5, 6, 8):
        return {"status": "specified", "owner": "po", "questions": [("po", False)]}
    if slot == 7:
        return {"status": "specified", "owner": "po", "questions": [("po", True)]}
    return {"status": "raw", "owner": "po", "questions": [("designer", True)]}


def feature_page(number: int, rng: random.Random) -> tuple[str, dict[str, str]]:
    """Render one feature page in the `_FORMAT.md` layout; return it with its index facts."""

    plan = feature_plan(number)
    subject = rng.choice(_SUBJECTS)
    title = f"{subject} {number:04d}"
    feature_id = f"F-{number:03d}"
    criteria = rng.randint(2, 5)
    rows = []
    for index, (owner, is_open) in enumerate(plan["questions"], start=1):
        question = rng.choice(_QUESTIONS)
        rows.append(f"| {index} | {question} | {owner} | {'open' if is_open else _ANSWER} |")
    page = (
        "---\n"
        f"id: {feature_id}\n"
        f"title: {title}\n"
        f"status: {plan['status']}\n"
        f"owner: {plan['owner']}\n"
        "apps:\n- backend\n"
        f"sources:\n- {PROCESSED_SOURCE}\n"
        "advisory-review: not-needed\n"
        "---\n\n"
        "## Summary\n"
        f"{subject}: review a document, summarize its key points, and record the review outcome.\n\n"
        "## User story\n"
        "As a reviewer, I want to record a document review, so that the outcome and follow-up are clear.\n\n"
        "## Acceptance criteria\n"
        + "".join(f"- [ ] Condition {i} for {title} can be checked without ambiguity.\n" for i in range(1, criteria + 1))
        + "\n## Open questions\n"
        "| # | Question | Owner | Status |\n"
        "|---|----------|-------|--------|\n"
        + "\n".join(rows)
        + "\n\n## App scope\n"
        "- **backend**: Store the review summary and recorded outcome.\n\n"
        "## API surface\nNone\n"
    )
    return page, {"id": feature_id, "title": title, "status": plan["status"], "owner": plan["owner"], "slug": _slug(title)}


def build_workspace(root: Path, count: int, seed: int = SEED) -> dict[str, Any]:
    """Create a workflow-adopted neutral workspace with ``count`` feature pages."""

    from prism_cli.workflow_install import apply_install, plan_install
    from tests.core_workflow_fixture import create_core_workflow_fixture

    create_core_workflow_fixture(root)
    receipt = apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
    if receipt["status"] != "applied":
        raise RuntimeError(f"workflow installer did not apply: {receipt.get('status')}")
    # The brief becomes a processed source so feature pages can cite it.
    (root / "knowledge/intake/pending/document-review-brief").rename(root / "knowledge/intake/processed/document-review-brief")
    # Use the shipped wiki schema for realistic sizes; the fixture has a placeholder.
    shutil.copyfile(REPO_ROOT / "template/knowledge/wiki/SCHEMA.md", root / "knowledge/wiki/SCHEMA.md")

    rng = random.Random(seed)
    features = root / "knowledge/wiki/features"
    index_rows = []
    counts = {"raw": 0, "specified": 0, "open_questions": 0}
    for number in range(1, count + 1):
        page, facts = feature_page(number, rng)
        (features / f"{facts['id']}-{facts['slug']}.md").write_text(page, encoding="utf-8", newline="\n")
        index_rows.append(f"| {facts['id']} | {facts['title']} | {facts['status']} | {facts['owner']} | not-needed |\n")
        counts[facts["status"]] += 1
        counts["open_questions"] += sum(1 for _owner, is_open in feature_plan(number)["questions"] if is_open)
    (root / "knowledge/wiki/index.md").write_text(
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review |\n"
        "|----|---------|--------|-------|--------------|\n" + "".join(index_rows),
        encoding="utf-8",
        newline="\n",
    )
    files = [path for path in (root / "knowledge").rglob("*") if path.is_file()]
    return {
        "features": count,
        "raw": counts["raw"],
        "specified": counts["specified"],
        "open_questions": counts["open_questions"],
        "knowledge_files": len(files),
        "knowledge_bytes": sum(path.stat().st_size for path in files),
    }


# --------------------------------------------------------------------------
# HTTP server under measurement
# --------------------------------------------------------------------------


class RunningBoard:
    """One BoardService + create_app served by uvicorn in a thread on loopback."""

    def __init__(self, workspace: Path, token: str) -> None:
        import uvicorn
        from prism_cli.board_server import create_app
        from prism_cli.board_service import BoardService

        self.token = token
        self.port = free_port()
        self.headers = {"Authorization": "Bearer " + token}
        self.timings: dict[str, float] = {}
        t0 = time.perf_counter()
        self.service = BoardService(workspace)
        t1 = time.perf_counter()
        self.app = create_app(workspace, port=self.port, service=self.service)
        t2 = time.perf_counter()
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="error",
            access_log=False,
            server_header=False,
            date_header=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="measure-board-uvicorn", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 60
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the board server did not start")
            time.sleep(0.005)
        t3 = time.perf_counter()
        body = self.fetch_data()
        t4 = time.perf_counter()
        if "envelope" not in body:
            raise RuntimeError("the first /data.json response had no graph envelope")
        self.timings = {
            "service_s": t1 - t0,
            "create_app_s": t2 - t1,
            "server_start_s": t3 - t2,
            "first_data_s": t4 - t3,
            "total_s": t4 - t0,
        }

    def connection(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)

    def fetch_data(self, conn: http.client.HTTPConnection | None = None) -> dict[str, Any]:
        own = conn is None
        conn = conn or self.connection()
        try:
            conn.request("GET", "/data.json", headers=self.headers)
            response = conn.getresponse()
            raw = response.read()
            if response.status != 200:
                raise RuntimeError(f"/data.json returned HTTP {response.status}")
            self.last_bytes = len(raw)
            return json.loads(raw)
        finally:
            if own:
                conn.close()

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            raise RuntimeError("the board server did not stop")


class ScanRecorder:
    """Wrap the shared poller's two scan calls to time each scan without changing product code."""

    def __init__(self, graph: Any) -> None:
        self.graph = graph
        self.validate: list[float] = []
        self.fingerprint: list[float] = []
        self.rebuilds = 0
        self._original_validate = graph._validate_inputs
        self._original_fingerprint = graph._fingerprint_fn
        self._original_build = graph._build_graph

    def install(self) -> None:
        def validate() -> None:
            start = time.perf_counter()
            try:
                self._original_validate()
            finally:
                self.validate.append(time.perf_counter() - start)

        def fingerprint(root: Path) -> Any:
            start = time.perf_counter()
            try:
                return self._original_fingerprint(root)
            finally:
                self.fingerprint.append(time.perf_counter() - start)

        def build(root: Path) -> Any:
            self.rebuilds += 1
            return self._original_build(root)

        self.graph._validate_inputs = validate
        self.graph._fingerprint_fn = fingerprint
        self.graph._build_graph = build

    def uninstall(self) -> None:
        self.graph._validate_inputs = self._original_validate
        self.graph._fingerprint_fn = self._original_fingerprint
        self.graph._build_graph = self._original_build

    def reset(self) -> None:
        self.validate = []
        self.fingerprint = []
        self.rebuilds = 0

    def scans(self) -> list[float]:
        """Each poll runs validate then fingerprint; with no rebuild they pair one to one."""

        return [v + f for v, f in zip(self.validate, self.fingerprint)]


def run_viewer_window(board: RunningBoard, recorder: ScanRecorder, mode: str, viewers: int, seconds: float) -> dict[str, Any]:
    """Hold ``viewers`` clients for ``seconds`` and report shared-scan time and process CPU."""

    stop = threading.Event()
    latencies: list[float] = []
    events: list[int] = [0]
    errors: list[str] = []
    lock = threading.Lock()

    def sse_viewer() -> None:
        conn = http.client.HTTPConnection("127.0.0.1", board.port, timeout=3)
        try:
            board.fetch_data()  # the browser loads the graph once, then follows the stream
            conn.request("GET", "/events", headers={**board.headers, "Accept": "text/event-stream"})
            response = conn.getresponse()
            if response.status != 200:
                raise RuntimeError(f"/events returned HTTP {response.status}")
            while not stop.is_set():
                try:
                    line = response.fp.readline()
                except (TimeoutError, socket.timeout):
                    continue
                if not line:
                    break
                if line.startswith(b"id:") or line.startswith(b": keep-alive"):
                    with lock:
                        events[0] += 1
        except Exception as exc:
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}"[:200])
        finally:
            conn.close()

    def poll_viewer() -> None:
        conn = board.connection()
        try:
            while not stop.is_set():
                started = time.perf_counter()
                board.fetch_data(conn)
                with lock:
                    latencies.append(time.perf_counter() - started)
                stop.wait(POLL_INTERVAL_SECONDS)
        except Exception as exc:
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}"[:200])
        finally:
            conn.close()

    target = {"sse": sse_viewer, "poll": poll_viewer}.get(mode)
    threads = [threading.Thread(target=target, name=f"measure-viewer-{index}", daemon=True) for index in range(viewers)] if target else []
    graph = board.app.state.board_graph
    version_before = graph.version
    recorder.reset()
    cpu_before = time.process_time()
    wall_before = time.perf_counter()
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    cpu_after = time.process_time()
    wall_after = time.perf_counter()
    scans = recorder.scans()
    rebuilds = recorder.rebuilds
    version_after = graph.version
    stop.set()
    for thread in threads:
        thread.join(timeout=10)
    if errors:
        raise RuntimeError(f"viewer errors in {mode} x{viewers}: {errors[:3]}")
    wall = wall_after - wall_before
    cpu = cpu_after - cpu_before
    result: dict[str, Any] = {
        "mode": mode,
        "viewers": viewers,
        "window_s": round(wall, 2),
        "process_cpu_s": round(cpu, 3),
        "process_cpu_pct_of_one_core": round(100.0 * cpu / wall, 1),
        "scans": len(scans),
        "scan_ms": stats_ms(scans),
        "scan_duty_pct": round(100.0 * sum(scans) / wall, 2),
        "graph_rebuilds": rebuilds,
        "graph_version_changes": version_after - version_before,
    }
    if mode == "poll":
        result["requests"] = len(latencies)
        result["request_ms"] = stats_ms(latencies)
    if mode == "sse":
        result["stream_events"] = events[0]
    return result


def measure_standalone_scan(board: RunningBoard, samples: int) -> dict[str, Any]:
    """Time the scan and a graph rebuild directly, outside any request, on the idle server."""

    graph = board.app.state.board_graph
    validate: list[float] = []
    fingerprint: list[float] = []
    scan: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        graph._validate_inputs()
        middle = time.perf_counter()
        graph._fingerprint_fn(graph.root)
        end = time.perf_counter()
        validate.append(middle - start)
        fingerprint.append(end - middle)
        scan.append(end - start)
    rebuild: list[float] = []
    for _ in range(min(samples, 10)):
        start = time.perf_counter()
        graph._build_graph(graph.root)
        rebuild.append(time.perf_counter() - start)
    return {"validate_ms": stats_ms(validate), "fingerprint_ms": stats_ms(fingerprint), "scan_ms": stats_ms(scan), "rebuild_ms": stats_ms(rebuild)}


# --------------------------------------------------------------------------
# MCP through the real SDK client over ASGI
# --------------------------------------------------------------------------


def _tool_data(result: Any, tool: str) -> dict[str, Any]:
    if result.is_error:
        text = " ".join(getattr(part, "text", "") for part in result.content)[:300]
        raise RuntimeError(f"MCP tool {tool} returned an error: {text}")
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(next(part.text for part in result.content if getattr(part, "type", None) == "text"))


class McpSession:
    """A BoardService + app + MCP SDK client over the ASGI transport, on one workspace copy."""

    def __init__(self, workspace: Path, token: str) -> None:
        self.workspace = workspace
        self.token = token

    async def __aenter__(self) -> "McpSession":
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from prism_cli.board_server import create_app
        from prism_cli.board_service import BoardService

        origin = f"http://127.0.0.1:{MCP_ORIGIN_PORT}"
        self.service = BoardService(self.workspace)
        self.app = create_app(self.workspace, port=MCP_ORIGIN_PORT, service=self.service)
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        transport = httpx2.ASGITransport(app=self.app)
        self._http = httpx2.AsyncClient(transport=transport, base_url=origin, headers={"Authorization": "Bearer " + self.token})
        await self._http.__aenter__()
        self._stream = streamable_http_client(origin + "/mcp", http_client=self._http)
        reader, writer = await self._stream.__aenter__()
        self.client = ClientSession(reader, writer)
        await self.client.__aenter__()
        await self.client.initialize()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        for closer in (self.client, self._stream, self._http, self._lifespan):
            try:
                await closer.__aexit__(None, None, None)
            except Exception:
                pass
        self.service.close()

    async def call(self, tool: str, arguments: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        start = time.perf_counter()
        result = await self.client.call_tool(tool, arguments)
        elapsed = time.perf_counter() - start
        return elapsed, _tool_data(result, tool)


def copy_workspace(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


async def measure_mcp(seed_workspace: Path, token: str, work: Path, samples: int, apply_samples: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    warmups = 3
    main_copy = copy_workspace(seed_workspace, work / f"mcp-main-{uuid.uuid4().hex[:8]}")
    plan: list[tuple[str, dict[str, Any], str]] = [
        ("discover", {}, "discover"),
        ("query", {"kind": "blockers"}, "query blockers"),
        ("get_skill", {"name": "po-intake"}, "get_skill po-intake"),
        ("preview_transition", {"feature_id": READY_FEATURE, "action": "po-handoff", "inputs": {"semantic_review_acknowledged": True}}, "preview_transition po-handoff"),
    ]
    async with McpSession(main_copy, token) as session:
        for tool, arguments, label in plan:
            for _ in range(warmups):
                await session.call(tool, arguments)
            durations: list[float] = []
            last: dict[str, Any] = {}
            for _ in range(samples):
                elapsed, last = await session.call(tool, arguments)
                durations.append(elapsed)
            entry = stats_ms(durations)
            entry["response_chars"] = compact_chars(last)
            if tool == "query":
                entry["total"] = last.get("total")
            if tool == "preview_transition":
                entry["applicable"] = last.get("applicable")
                entry["classification"] = last.get("classification")
                if last.get("applicable") is not True:
                    raise RuntimeError(f"po-handoff preview for {READY_FEATURE} was not applicable: {last.get('classification')}")
            results[label] = entry
    shutil.rmtree(main_copy, ignore_errors=True)

    apply_durations: list[float] = []
    apply_chars = 0
    for _ in range(apply_samples):
        copy = copy_workspace(seed_workspace, work / f"mcp-apply-{uuid.uuid4().hex[:8]}")
        try:
            async with McpSession(copy, token) as session:
                _elapsed, preview = await session.call(
                    "preview_transition",
                    {"feature_id": READY_FEATURE, "action": "po-handoff", "inputs": {"semantic_review_acknowledged": True}},
                )
                if preview.get("applicable") is not True:
                    raise RuntimeError(f"po-handoff preview was not applicable: {preview.get('classification')}")
                elapsed, applied = await session.call("apply", {"preview_id": preview["preview_id"], "operation_id": "scale-" + uuid.uuid4().hex})
                if applied.get("state") != "applied":
                    raise RuntimeError(f"apply did not apply: {applied.get('state')}")
                apply_durations.append(elapsed)
                apply_chars = compact_chars(applied)
        finally:
            shutil.rmtree(copy, ignore_errors=True)
    entry = stats_ms(apply_durations)
    entry["response_chars"] = apply_chars
    entry["note"] = "fresh workspace copy per repetition"
    results["apply po-handoff"] = entry
    return results


# --------------------------------------------------------------------------
# One size, in a worker process
# --------------------------------------------------------------------------


def measure_size(size: int, pristine: Path, work: Path, samples: int, apply_samples: int, cold_runs: int) -> dict[str, Any]:
    from prism_cli.board_service import BoardService

    logging.disable(logging.CRITICAL)
    baseline_rss = current_rss_bytes()

    # Seed one human, writable grant into the pristine copy so every disposable
    # copy carries it and grant creation stays out of the timed cold start.
    seed = copy_workspace(pristine, work / "seed")
    with BoardService(seed) as service:
        token = service.create_participant(f"Scale {size}", "human", writable=True)["token"]
    mem_after_seed = current_rss_bytes()

    result: dict[str, Any] = {"features": size, "samples": samples}

    # Cold start: the first run in the process also pays for lazy imports.
    cold: list[dict[str, float]] = []
    board: RunningBoard | None = None
    try:
        for run in range(cold_runs):
            copy = copy_workspace(seed, work / f"http-{run}")
            candidate = RunningBoard(copy, token)
            cold.append({key: round(value * 1000.0, 2) for key, value in candidate.timings.items()})
            if run == cold_runs - 1:
                board = candidate
            else:
                candidate.stop()
                shutil.rmtree(copy, ignore_errors=True)
        assert board is not None
        totals = [item["total_s"] for item in cold]
        result["cold_start"] = {
            "runs": cold,
            "first_run_total_ms": cold[0]["total_s"],
            "median_total_ms": round(statistics.median(totals), 2),
            "max_total_ms": max(totals),
            "note": "BoardService() to first 200 /data.json; the first run also pays lazy imports and a cold process",
        }

        # /data.json latency over the loopback socket, keep-alive connection.
        conn = board.connection()
        try:
            for _ in range(WARMUP_REQUESTS):
                board.fetch_data(conn)
            durations = []
            for _ in range(samples):
                started = time.perf_counter()
                board.fetch_data(conn)
                durations.append(time.perf_counter() - started)
        finally:
            conn.close()
        data_stats = stats_ms(durations)
        data_stats["response_bytes"] = board.last_bytes
        result["data_json"] = data_stats

        # Shared scan: direct timing first (idle), then under viewers.
        result["scan_standalone"] = measure_standalone_scan(board, samples)
        recorder = ScanRecorder(board.app.state.board_graph)
        recorder.install()
        windows = [run_viewer_window(board, recorder, "idle", 0, VIEWER_WINDOW_SECONDS)]
        for mode in ("sse", "poll"):
            for viewers in VIEWER_COUNTS:
                windows.append(run_viewer_window(board, recorder, mode, viewers, VIEWER_WINDOW_SECONDS))
        recorder.uninstall()
        result["viewer_windows"] = windows
    finally:
        if board is not None:
            board.stop()
    mem_after_http = current_rss_bytes()

    result["mcp"] = asyncio.run(measure_mcp(seed, token, work, samples, apply_samples))

    result["memory"] = {
        "baseline_rss_mib": _mib(baseline_rss),
        "rss_after_seed_mib": _mib(mem_after_seed),
        "rss_after_http_mib": _mib(mem_after_http),
        "rss_end_mib": _mib(current_rss_bytes()),
        "peak_rss_mib": _mib(peak_rss_bytes()),
        "note": "peak working set of the worker process: server, viewer clients, MCP client and two services together",
    }
    return result


def worker_main(args: argparse.Namespace) -> int:
    result = measure_size(args.size, Path(args.pristine), Path(args.work), args.samples, args.apply_samples, args.cold_runs)
    Path(args.result).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def _row(label: str, entry: dict[str, Any], note: str = "") -> str:
    if not entry or not entry.get("n"):
        return f"| {label} | 0 | - | - | - | {note} |"
    return f"| {label} | {entry['n']} | {_fmt(entry['p50'])} | {_fmt(entry['p95'])} | {_fmt(entry['max'])} | {note} |"


def size_table(result: dict[str, Any], build: dict[str, Any]) -> list[str]:
    cold = result["cold_start"]
    lines = [
        f"## {result['features']} features",
        "",
        f"Workspace: {build['specified']} specified, {build['raw']} raw, {build['open_questions']} open questions, "
        f"{build['knowledge_files']} files / {build['knowledge_bytes']:,} bytes under `knowledge/`. "
        f"`/data.json` body: {result['data_json']['response_bytes']:,} bytes.",
        "",
        "Times in milliseconds. n is the number of samples (cold start: runs).",
        "",
        "| Measurement | n | p50 | p95 | max | Notes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    totals = [item["total_s"] for item in cold["runs"]]
    lines.append(
        f"| Cold start (BoardService to first /data.json) | {len(totals)} | {_fmt(statistics.median(totals))} | - | {_fmt(max(totals))} | "
        f"first run {_fmt(cold['first_run_total_ms'])}; p50 column is the median of runs |"
    )
    first = cold["runs"][0]
    lines.append(
        f"| Cold start, first run phases | 1 | - | - | - | BoardService {_fmt(first['service_s'])}, create_app (graph build) {_fmt(first['create_app_s'])}, "
        f"server start {_fmt(first['server_start_s'])}, first /data.json {_fmt(first['first_data_s'])} |"
    )
    lines.append(_row("/data.json request", result["data_json"], "keep-alive loopback request, 5 warm-up requests excluded"))
    scan = result["scan_standalone"]
    lines.append(_row("Shared scan, idle (validate + fingerprint)", scan["scan_ms"], f"validate p50 {_fmt(scan['validate_ms']['p50'])}, fingerprint p50 {_fmt(scan['fingerprint_ms']['p50'])}"))
    lines.append(_row("Graph rebuild (runs only when a file changed)", scan["rebuild_ms"], "build_graph, one call"))
    for label, entry in result["mcp"].items():
        notes = [f"{entry.get('response_chars', 0):,} chars"]
        if entry.get("total") is not None:
            notes.append(f"total {entry['total']}")
        if entry.get("note"):
            notes.append(entry["note"])
        lines.append(_row(f"MCP {label}", entry, ", ".join(notes)))
    lines += [
        "",
        f"Shared scan and process CPU over {VIEWER_WINDOW_SECONDS:.0f}-second windows. `sse` viewers load the graph once and hold `/events` (the browser behaviour); "
        f"`poll` viewers fetch `/data.json` every {POLL_INTERVAL_SECONDS} s. CPU is process-wide, so it includes the measuring client threads.",
        "",
        "| Viewers | Behaviour | Scans | Scan p50 ms | Scan p95 ms | Scan max ms | Scan duty % | Process CPU s | CPU % of one core | Rebuilds | Request p50 / p95 ms |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for window in result["viewer_windows"]:
        scan_ms = window["scan_ms"]
        request = window.get("request_ms")
        request_text = f"{_fmt(request['p50'])} / {_fmt(request['p95'])}" if request and request.get("n") else "-"
        lines.append(
            f"| {window['viewers']} | {window['mode']} | {window['scans']} | {_fmt(scan_ms.get('p50'))} | {_fmt(scan_ms.get('p95'))} | {_fmt(scan_ms.get('max'))} | "
            f"{_fmt(window['scan_duty_pct'], 2)} | {_fmt(window['process_cpu_s'], 3)} | {_fmt(window['process_cpu_pct_of_one_core'])} | {window['graph_rebuilds']} | {request_text} |"
        )
    memory = result["memory"]
    lines += [
        "",
        f"Memory (MiB): baseline after imports {_fmt(memory['baseline_rss_mib'])}, after HTTP phase {_fmt(memory['rss_after_http_mib'])}, "
        f"end {_fmt(memory['rss_end_mib'])}, **peak {_fmt(memory['peak_rss_mib'])}**.",
        "",
    ]
    return lines


GROWTH_METRICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Cold start median (ms)", ("cold_start", "median_total_ms")),
    ("/data.json p50 (ms)", ("data_json", "p50")),
    ("/data.json p95 (ms)", ("data_json", "p95")),
    ("/data.json bytes", ("data_json", "response_bytes")),
    ("Shared scan p50, idle (ms)", ("scan_standalone", "scan_ms", "p50")),
    ("Graph rebuild p50 (ms)", ("scan_standalone", "rebuild_ms", "p50")),
    ("MCP discover p50 (ms)", ("mcp", "discover", "p50")),
    ("MCP query blockers p50 (ms)", ("mcp", "query blockers", "p50")),
    ("MCP get_skill p50 (ms)", ("mcp", "get_skill po-intake", "p50")),
    ("MCP preview_transition p50 (ms)", ("mcp", "preview_transition po-handoff", "p50")),
    ("MCP apply p50 (ms)", ("mcp", "apply po-handoff", "p50")),
    ("Peak RSS (MiB)", ("memory", "peak_rss_mib")),
)


def _dig(result: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = result
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def growth_table(results: list[dict[str, Any]]) -> list[str]:
    """Across-size view: values per size and the growth factor of each step relative to the size ratio."""

    if len(results) < 2:
        return []
    sizes = [item["features"] for item in results]
    header = ["Metric", *[str(size) for size in sizes], *[f"x{b}/{a}" for a, b in zip(sizes, sizes[1:])]]
    lines = [
        "## Growth across sizes",
        "",
        "The step columns divide the metric's growth by the growth in feature count for that step: about 1.0 is linear, "
        "above about 1.3 grows faster than the workspace, below 1.0 is dominated by fixed overhead. Small absolute values are noisy.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] + ["---:"] * (len(header) - 1)) + "|",
    ]
    for label, path in GROWTH_METRICS:
        values = [_dig(item, path) for item in results]
        cells = [_fmt(value) for value in values]
        for (a, va), (b, vb) in zip(zip(sizes, values), zip(sizes[1:], values[1:])):
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va > 0:
                factor = (vb / va) / (b / a)
                cells.append(f"{factor:.2f}" + (" (super-linear)" if factor > 1.3 and vb > 5 else ""))
            else:
                cells.append("-")
        lines.append("| " + " | ".join([label, *cells]) + " |")
    lines.append("")
    return lines


def write_reports(out: Path, info: dict[str, Any], builds: dict[int, dict[str, Any]], results: list[dict[str, Any]], args: argparse.Namespace) -> None:
    payload = {
        "machine": info,
        "parameters": {
            "sizes": [item["features"] for item in results],
            "samples": args.samples,
            "apply_samples": args.apply_samples,
            "cold_runs": args.cold_runs,
            "warmup_requests": WARMUP_REQUESTS,
            "viewer_window_seconds": VIEWER_WINDOW_SECONDS,
            "viewer_counts": list(VIEWER_COUNTS),
            "poll_interval_seconds": POLL_INTERVAL_SECONDS,
            "seed": SEED,
        },
        "workspaces": {str(size): build for size, build in builds.items()},
        "results": results,
    }
    (out / "scale-results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Board scale measurement",
        "",
        "## Machine",
        "",
        f"- OS: {info['os']}",
        f"- CPU: {info['cpu_model']} ({info['cpu_cores_logical']} logical cores)",
        f"- RAM: {_fmt(info['ram_gib'])} GiB",
        f"- Python: {info['python_implementation']} {info['python']}",
        f"- Prism version: {info['prism_version']}",
        f"- Git commit: {info['git_commit']}",
        "",
        "## Method",
        "",
        f"Deterministic neutral workspaces (seed {SEED}), one worker process per size. HTTP is served by uvicorn in a thread on a loopback socket; "
        "MCP goes through the real SDK client over the ASGI transport. Each timed phase works on a disposable copy of the workspace. "
        f"Samples per repeated measurement: {args.samples} after warm-up; `apply` runs {args.apply_samples} times, each on a fresh copy. "
        "The measuring client shares the process and the GIL with the server thread, so latencies and CPU are an upper bound for the server alone.",
        "",
    ]
    for result in results:
        lines += size_table(result, builds[result["features"]])
    lines += growth_table(results)
    (out / "scale-results.md").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure Prism board behaviour as a workspace grows.")
    parser.add_argument("--out", help="Directory for scale-results.json, scale-results.md and temporary workspaces.")
    parser.add_argument("--sizes", default=",".join(str(size) for size in DEFAULT_SIZES), help="Comma-separated feature counts.")
    parser.add_argument("--samples", type=int, default=50, help="Requests per repeated measurement after warm-up.")
    parser.add_argument("--apply-samples", type=int, default=5, help="Repetitions of apply, each on a fresh workspace copy.")
    parser.add_argument("--cold-runs", type=int, default=3, help="Cold-start repetitions per size (the last one stays up for the other HTTP measurements).")
    parser.add_argument("--keep-workspaces", action="store_true", help="Keep the temporary workspaces under --out/work.")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--pristine", help=argparse.SUPPRESS)
    parser.add_argument("--work", help=argparse.SUPPRESS)
    parser.add_argument("--result", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.samples < 1 or args.apply_samples < 1 or args.cold_runs < 1:
        parser.error("--samples, --apply-samples and --cold-runs must be at least 1")
    if not args.worker and not args.out:
        parser.error("--out is required")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.worker:
        return worker_main(args)
    try:
        sizes = sorted({int(item) for item in args.sizes.split(",") if item.strip()})
    except ValueError:
        print("--sizes must be comma-separated integers", file=sys.stderr)
        return 2
    if not sizes or sizes[0] < 1:
        print("--sizes needs at least one positive size", file=sys.stderr)
        return 2

    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    work_root = out / "work"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir()

    logging.disable(logging.CRITICAL)
    info = machine_info()
    print(f"Prism {info['prism_version']}  git {info['git_commit']}")
    builds: dict[int, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    try:
        for size in sizes:
            size_dir = work_root / f"size-{size}"
            size_dir.mkdir()
            pristine = size_dir / "pristine"
            print(f"[{size}] building workspace", flush=True)
            builds[size] = build_workspace(pristine, size)
            run_dir = size_dir / "run"
            run_dir.mkdir()
            result_file = size_dir / "result.json"
            command = [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--worker",
                "--size",
                str(size),
                "--pristine",
                str(pristine),
                "--work",
                str(run_dir),
                "--result",
                str(result_file),
                "--samples",
                str(args.samples),
                "--apply-samples",
                str(args.apply_samples),
                "--cold-runs",
                str(args.cold_runs),
            ]
            print(f"[{size}] measuring", flush=True)
            completed = subprocess.run(command, cwd=str(REPO_ROOT))
            if completed.returncode != 0 or not result_file.exists():
                print(f"[{size}] worker failed with exit code {completed.returncode}", file=sys.stderr)
                return 1
            results.append(json.loads(result_file.read_text(encoding="utf-8")))
            if not args.keep_workspaces:
                shutil.rmtree(size_dir, ignore_errors=True)
        write_reports(out, info, builds, results, args)
    finally:
        if not args.keep_workspaces:
            shutil.rmtree(work_root, ignore_errors=True)
    print(f"Wrote {out / 'scale-results.json'} and {out / 'scale-results.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
