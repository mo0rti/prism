"""Shared fixture for real-browser board tests.

The fixture builds a disposable neutral workspace, serves the real
``create_app`` ASGI app with uvicorn on a free loopback port in a background
thread, and drives it with a clean Playwright Chromium profile. Participant
tokens stay in memory: they are never written to disk, logged or put in
evidence, and every scenario scans its evidence for them before it finishes.

Environment variables
---------------------
``PRISM_BROWSER_E2E=1``
    Enables the tests. Without it, and without an importable ``playwright``,
    every test here is skipped and the default suite stays dependency-free.
``PRISM_BROWSER_E2E_DIR``
    Folder for disposable workspaces (``work/``) and evidence (``artifacts/``).
    Defaults to ``<system temp>/prism-browser-e2e``.
``PRISM_BROWSER_E2E_EXECUTABLE``
    Optional Chromium executable for ``chromium.launch(executable_path=...)``.
    Without it Playwright uses its bundled browser. Playwright still starts the
    executable with a fresh profile and no extensions.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
from typing import Any, Iterator
import unittest
from unittest.mock import Mock, patch
import zipfile

from prism_cli.board_server import create_app
from prism_cli.board_service import BoardService
from prism_cli.workflow_install import apply_install, plan_install
from tests.core_workflow_fixture import INTAKE_ITEM, PROCESSED_INTAKE_ITEM, create_core_workflow_fixture
from tests.test_core_workflow_fixture import CHECK_DATE, _feature_page, _requirement_page
from tests.wiki_files import write_index


ENABLE_VARIABLE = "PRISM_BROWSER_E2E"
DIRECTORY_VARIABLE = "PRISM_BROWSER_E2E_DIR"
EXECUTABLE_VARIABLE = "PRISM_BROWSER_E2E_EXECUTABLE"
STEP_TIMEOUT_MS = 20_000


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def browser_e2e_enabled() -> bool:
    return os.environ.get(ENABLE_VARIABLE) == "1" and playwright_available()


requires_browser_e2e = unittest.skipUnless(
    browser_e2e_enabled(),
    f"Set {ENABLE_VARIABLE}=1 and install the optional `e2e` extra (playwright) to run browser tests.",
)


def e2e_directory() -> Path:
    configured = os.environ.get(DIRECTORY_VARIABLE)
    base = Path(configured) if configured else Path(tempfile.gettempdir()) / "prism-browser-e2e"
    return base.expanduser().resolve()


@dataclass(frozen=True)
class FixtureFeature:
    feature_id: str
    title: str
    status: str
    owner: str
    # Extras only: leave the page's one open question open, or start the
    # advisory review as ``pending``. The default features keep both clear.
    question_open: bool = False
    advisory: str = "not-needed"

    @property
    def path(self) -> Path:
        return Path(f"knowledge/wiki/features/{self.feature_id}-document-review.md")


# One feature per connected human action so every scenario starts from the
# same disposable stages: ready for po-handoff, design-start and dev-start.
# F-004 is a byte-for-byte twin of F-001 (same title and body, different ID),
# so one session can compare a pointer-driven and a keyboard-driven po-handoff.
FEATURES = (
    FixtureFeature("F-001", "Document review", "specified", "po"),
    FixtureFeature("F-002", "Document summary", "ready-for-design", "designer"),
    FixtureFeature("F-003", "Review follow-up", "ready-for-dev", "dev"),
    FixtureFeature("F-004", "Document review", "specified", "po"),
)
FEATURES_BY_ID = {feature.feature_id: feature for feature in FEATURES}

# Optional extras a test class opts into with ``extra_features``. They are never
# part of the default workspace, so scenarios A and B see exactly F-001..F-004.
EXTRA_FEATURES = {
    # An open question blocks po-handoff: a drop on its destination is blocked.
    "blocked": FixtureFeature("F-005", "Blocked question", "specified", "po", question_open=True),
    # A pending advisory review adds the skip proposal and its reason textarea.
    "advisory": FixtureFeature("F-006", "Advisory handoff", "specified", "po", advisory="pending"),
    # Agent-only lifecycle actions: the board offers a request, not a human apply.
    "in-design": FixtureFeature("F-007", "Design in progress", "in-design", "designer"),
    "raw": FixtureFeature("F-008", "Raw idea", "raw", "po", question_open=True),
    "in-dev": FixtureFeature("F-009", "Development in progress", "in-dev", "dev"),
}


@contextmanager
def frozen_clock() -> Iterator[None]:
    """Pin the lifecycle clock to the fixture date, as the parity tests do."""

    clock = Mock(wraps=date)
    clock.today.return_value = CHECK_DATE
    with ExitStack() as stack:
        for module in ("board_service", "wiki_lint", "wiki_transitions"):
            stack.enter_context(patch(f"prism_cli.{module}.date", clock))
        yield


def _feature_page_for(feature: FixtureFeature) -> str:
    content = _feature_page().replace("id: F-001\n", f"id: {feature.feature_id}\n", 1)
    content = content.replace("title: Document review\n", f"title: {feature.title}\n", 1)
    content = content.replace("status: raw\n", f"status: {feature.status}\n", 1).replace("owner: po\n", f"owner: {feature.owner}\n", 1)
    content = content.replace("advisory-review: not-needed\n", f"advisory-review: {feature.advisory}\n", 1)
    if feature.question_open:
        return content
    # Resolved questions keep every action ready, so scenarios exercise the
    # preview and apply path rather than the blocked-preview path.
    return content.replace("| po | open |", "| po | resolved: Capture key points and requested follow-up. |")


def _board_text(features: tuple[FixtureFeature, ...]) -> str:
    rows = "".join(
        f"| {feature.feature_id} | {feature.title} | {feature.status} | {feature.owner} | {feature.advisory} |\n"
        for feature in features
    )
    return (
        "# Feature Status Board\n\n"
        "| ID | Feature | Status | Owner | Board Review |\n"
        "|----|---------|--------|-------|--------------|\n" + rows
    )


def build_workspace(root: Path, extras: tuple[FixtureFeature, ...] = ()) -> Path:
    """Create an adopted neutral workspace with one feature per human action.

    ``extras`` adds more features after the defaults; none by default.
    """

    create_core_workflow_fixture(root)
    receipt = apply_install(root, plan_install(root, name="Document review", apps=["backend"]))
    if receipt["status"] != "applied":
        raise RuntimeError(f"Workflow install did not apply: {receipt['status']}")
    (root / INTAKE_ITEM.parent).rename(root / PROCESSED_INTAKE_ITEM.parent)
    features = FEATURES + tuple(extras)
    for feature in features:
        target = root / feature.path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Canonical LF bytes keep before/after comparisons independent of the
        # platform's newline translation.
        target.write_bytes(_feature_page_for(feature).encode("utf-8"))
    (root / "knowledge/wiki/status-board.md").write_bytes(_board_text(features).encode("utf-8"))
    requirement = _requirement_page("pending").replace("feature-id: F-001", "feature-id: F-003", 1)
    (root / "knowledge/wiki/app-requirements/F-003-backend.md").write_bytes(requirement.encode("utf-8"))
    # The general index lists every page the workspace holds, so lint is clean and the board writes only what an action changes.
    write_index(root)
    return root


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class DropProxy:
    """A loopback TCP relay that can cut live connections, like a flaky network.

    The browser talks to the relay's port; the relay forwards bytes untouched
    (Host and Origin included) to the board. ``pause`` drops every open
    connection, event stream included, and refuses new ones until ``resume``.
    """

    def __init__(self, listen_port: int, target_port: int) -> None:
        self._listen_port = listen_port
        self._target_port = target_port
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._pairs: list[tuple[socket.socket, socket.socket]] = []
        self._paused = False
        self._closed = False
        # Connections relayed so far; a test waits on it to see the browser try again.
        self.accepted = 0

    def start(self) -> "DropProxy":
        listener = socket.socket()
        listener.bind(("127.0.0.1", self._listen_port))
        listener.listen(32)
        self._listener = listener
        self._thread = threading.Thread(target=self._accept, name="prism-browser-e2e-relay", daemon=True)
        self._thread.start()
        return self

    def _accept(self) -> None:
        assert self._listener is not None
        while not self._closed:
            try:
                client, _address = self._listener.accept()
            except OSError:
                return
            if self._paused:
                client.close()
                continue
            try:
                upstream = socket.create_connection(("127.0.0.1", self._target_port), timeout=5)
            except OSError:
                client.close()
                continue
            upstream.settimeout(None)
            with self._lock:
                self._pairs.append((client, upstream))
                self.accepted += 1
            for source, sink in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pump, args=(source, sink), name="prism-browser-e2e-pump", daemon=True).start()

    @staticmethod
    def _pump(source: socket.socket, sink: socket.socket) -> None:
        try:
            while True:
                chunk = source.recv(65536)
                if not chunk:
                    break
                sink.sendall(chunk)
        except OSError:
            pass
        finally:
            for sock in (source, sink):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

    def drop_connections(self) -> None:
        with self._lock:
            pairs, self._pairs = self._pairs, []
        for pair in pairs:
            for sock in pair:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

    def pause(self) -> None:
        self._paused = True
        self.drop_connections()

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._closed = True
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        self.drop_connections()
        if self._thread is not None:
            self._thread.join(timeout=5)


class BoardHarness:
    """A served board for one disposable workspace.

    ``service`` is the same BoardService instance the app uses, so tests can
    read operation receipts through the service without a second process.
    ``stop_server`` and ``start_server`` restart the listener on the same port
    like a restarted ``prism board serve``: a new service and app over the same
    workspace and journal, so grants survive and browser sessions do not.
    """

    def __init__(self, work_directory: Path, extras: tuple[FixtureFeature, ...] = (), *, relay: bool = False) -> None:
        self.work_directory = work_directory
        self.extras = tuple(extras)
        self.root: Path | None = None
        self.service: BoardService | None = None
        # The public port is the one in the board URL and in Host/Origin checks.
        # With a relay the board listens on ``backend_port`` behind it.
        self.port = 0
        self.backend_port = 0
        self.use_relay = relay
        self.relay: DropProxy | None = None
        self._tokens: dict[str, str] = {}
        self._actors: dict[str, Any] = {}
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._clock = ExitStack()
        self._workspace_parent: Path | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def token(self, kind: str) -> str:
        return self._tokens[kind]

    def actor(self, kind: str) -> Any:
        return self._actors[kind]

    @property
    def secrets(self) -> list[str]:
        return list(self._tokens.values())

    def read(self, relative: str | Path) -> str:
        assert self.root is not None
        return (self.root / relative).read_bytes().decode("utf-8")

    def write(self, relative: str | Path, text: str) -> None:
        """An external edit, as a person with an editor would make it."""

        assert self.root is not None
        (self.root / relative).write_bytes(text.encode("utf-8"))

    # -- participants -------------------------------------------------------------

    def add_participant(self, label: str, kind: str, *, writable: bool = True) -> Any:
        """Issue a grant through the service. The token stays in memory under ``label``."""

        assert self.service is not None
        grant = self.service.create_participant(f"Browser {label}", kind, writable=writable)
        self._tokens[label] = grant["token"]
        self._actors[label] = self.service.authenticate(grant["token"])
        return self._actors[label]

    def revoke(self, label: str) -> None:
        assert self.service is not None
        self.service.revoke_participant(self._actors[label].participant_id)

    # -- server lifecycle ---------------------------------------------------------

    def _launch(self) -> None:
        import uvicorn

        assert self.root is not None
        service = BoardService(self.root)
        self.service = service
        service.start()
        app = create_app(self.root, port=self.port, service=service)
        # A short graceful-shutdown window lets a restart close open event streams
        # instead of waiting for the browser to hang up.
        config = uvicorn.Config(app, host="127.0.0.1", port=self.backend_port, log_level="error", access_log=False, lifespan="on", timeout_graceful_shutdown=2)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="prism-browser-e2e-board", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 30
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("The board server did not start.")
            time.sleep(0.05)

    def start(self) -> "BoardHarness":
        self.work_directory.mkdir(parents=True, exist_ok=True)
        self._workspace_parent = Path(tempfile.mkdtemp(prefix="board-", dir=self.work_directory))
        self._clock.enter_context(frozen_clock())
        try:
            self.root = build_workspace(self._workspace_parent / "document-review", self.extras)
            self.port = free_port()
            self.backend_port = self.port
            while self.use_relay and self.backend_port == self.port:
                self.backend_port = free_port()
            if self.use_relay:
                self.relay = DropProxy(self.port, self.backend_port).start()
            # The first launch builds the journal; participants are issued after it.
            self._launch()
            for kind in ("human", "agent"):
                self.add_participant(kind, kind)
        except BaseException:
            self.stop()
            raise
        return self

    def stop_server(self) -> None:
        """Stop listening. The app's shutdown also closes its service and releases the workspace lock."""

        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._server = None
        self._thread = None

    def start_server(self) -> None:
        """Serve the same workspace on the same port with a new service and a fresh session table."""

        self._launch()

    def restart_server(self) -> None:
        self.stop_server()
        self.start_server()

    def stop(self) -> None:
        if self.relay is not None:
            self.relay.stop()
        self.stop_server()
        if self.service is not None:
            self.service.close()
        self._clock.close()
        if self._workspace_parent is not None:
            shutil.rmtree(self._workspace_parent, ignore_errors=True)

    def __enter__(self) -> "BoardHarness":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.stop()


def assert_secrets_absent(directory: Path, secrets: list[str]) -> None:
    """Fail when any participant token appears in a file under ``directory``."""

    needles = [secret.encode("utf-8") for secret in secrets if secret]
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        chunks = [path.read_bytes()]
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                chunks = [archive.read(name) for name in archive.namelist()]
        for blob in chunks:
            if any(needle in blob for needle in needles):
                raise AssertionError(f"A participant token leaked into evidence file {path.name}.")


def redact_zip(path: Path, secrets: list[str]) -> None:
    """Rewrite a Playwright trace with each secret replaced, so session credentials never persist.

    If the rewrite cannot be completed the trace is deleted: an unredacted
    trace must never be left behind.
    """

    needles = [secret.encode("utf-8") for secret in secrets if secret]
    if not needles or not path.is_file():
        return
    temporary = path.with_suffix(".redacted")
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                blob = source.read(item.filename)
                for needle in needles:
                    blob = blob.replace(needle, b"<redacted>")
                target.writestr(item.filename, blob)
        # Windows can briefly deny the swap while the browser driver or a scanner still holds the file.
        deadline = time.monotonic() + 10
        while True:
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
    except Exception:
        for leftover in (temporary, path):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass


@dataclass
class Viewer:
    """One more browser context in a scenario: a second person, or another theme and size."""

    label: str
    context: Any
    page: Any
    traced: bool = False


class ScenarioRun:
    """Evidence for one scenario: trace, screenshot and ``summary.json``.

    The primary context writes ``trace.zip`` and ``screenshot.png``. Each extra
    viewer (see ``BrowserCase.new_viewer``) writes ``trace-<label>.zip`` and
    ``screenshot-<label>.png``. ``screenshot`` saves a named capture on demand.
    """

    def __init__(self, case: "BrowserCase", scenario: str, defect: str | None = None) -> None:
        self.case = case
        self.scenario = scenario
        # Set for a scenario that documents a known product defect; the test is
        # marked ``expectedFailure`` and the summary says which defect it shows.
        self.defect = defect
        self.directory = e2e_directory() / "artifacts" / scenario
        self.effects: list[str] = []
        self.captures: list[str] = []
        self.started = 0.0

    def effect(self, description: str) -> None:
        """Record one file effect or invariant this scenario verified."""

        self.effects.append(description)

    def screenshot(self, page: Any, name: str, *, full_page: bool = True) -> Path:
        """Save ``name``.png in this scenario's evidence folder."""

        path = self.directory / f"{name}.png"
        page.screenshot(path=str(path), full_page=full_page)
        self.captures.append(path.name)
        return path

    def __enter__(self) -> "ScenarioRun":
        if self.directory.exists():
            shutil.rmtree(self.directory)
        self.directory.mkdir(parents=True)
        self.started = time.monotonic()
        return self

    def __exit__(self, exc_type: Any, exc: Any, _tb: Any) -> None:
        result = "pass" if exc_type is None else "fail"
        targets = [("", self.case.context, self.case.page, True)]
        targets += [(f"-{viewer.label}", viewer.context, viewer.page, viewer.traced) for viewer in self.case.viewers]
        session_secrets = self.case.session_secrets()
        for suffix, context, page, traced in targets:
            if page is not None:
                try:
                    page.screenshot(path=str(self.directory / f"screenshot{suffix}.png"), full_page=True)
                except Exception:
                    pass
            if context is not None and traced:
                try:
                    context.tracing.stop(path=str(self.directory / f"trace{suffix}.zip"))
                except Exception:
                    pass
        # The trace records request headers, which carry the board's session
        # cookie and CSRF token. They die with the disposable server, but they
        # are credentials all the same, so redact them before anything persists.
        # Any ``trace*.zip`` here is covered, including chunks saved around a re-sign-in.
        for trace in sorted(self.directory.glob("trace*.zip")):
            redact_zip(trace, session_secrets)
        summary = {
            "scenario": self.scenario,
            "result": result,
            "duration_seconds": round(time.monotonic() - self.started, 3),
            "file_effects_checked": self.effects,
            "captures": self.captures,
            "known_defect": self.defect,
            "browser": self.case.browser_version,
            "failure": None if exc is None else f"{exc_type.__name__}: {str(exc)[:500]}",
        }
        (self.directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        tokens = self.case.harness.secrets if self.case.harness else []
        assert_secrets_absent(self.directory, tokens + session_secrets)


class BrowserCase(unittest.TestCase):
    """Base case: one clean browser per class, one served workspace per test."""

    playwright: Any = None
    browser: Any = None
    browser_version = ""

    # Subclasses that start their own server (for example through the CLI)
    # set this to False so no in-process board is served for them.
    serve_in_process = True
    # Extra workspace features for this class's tests; see ``EXTRA_FEATURES``.
    extra_features: tuple[FixtureFeature, ...] = ()
    # Put a connection-dropping relay between the browser and the board.
    use_relay = False
    viewport = {"width": 1500, "height": 950}

    harness: BoardHarness | None
    context: Any
    page: Any

    @classmethod
    def setUpClass(cls) -> None:
        from playwright.sync_api import expect, sync_playwright

        expect.set_options(timeout=STEP_TIMEOUT_MS)
        cls.playwright = sync_playwright().start()
        try:
            executable = os.environ.get(EXECUTABLE_VARIABLE) or None
            cls.browser = cls.playwright.chromium.launch(executable_path=executable, headless=True)
        except BaseException:
            cls.playwright.stop()
            raise
        cls.browser_version = cls.browser.version

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.browser is not None:
            cls.browser.close()
        if cls.playwright is not None:
            cls.playwright.stop()

    def setUp(self) -> None:
        self.harness = None
        self.context = None
        self.page = None
        self.viewers: list[Viewer] = []
        self._seen_secrets: set[str] = set()
        if self.serve_in_process:
            self.harness = BoardHarness(e2e_directory() / "work", self.extra_features, relay=self.use_relay)
            self.addCleanup(self.harness.stop)
            self.harness.start()
        # A fresh context is a fresh profile: no cookies, storage or extensions.
        self.context = self.browser.new_context(viewport=dict(self.viewport), service_workers="block")
        self.context.set_default_timeout(STEP_TIMEOUT_MS)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page_errors: list[str] = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))

    def new_viewer(self, label: str, **context_options: Any) -> Viewer:
        """Another clean browser profile with its own cookies, for a second person or a variant."""

        options: dict[str, Any] = {"viewport": dict(self.viewport), "service_workers": "block"}
        options.update(context_options)
        context = self.browser.new_context(**options)
        context.set_default_timeout(STEP_TIMEOUT_MS)
        self.addCleanup(context.close)
        page = context.new_page()
        page.on("pageerror", lambda error: self.page_errors.append(f"{label}: {error}"))
        viewer = Viewer(label, context, page)
        self.viewers.append(viewer)
        return viewer

    def scenario(self, name: str, defect: str | None = None) -> ScenarioRun:
        return ScenarioRun(self, name, defect)

    def session_secrets(self) -> list[str]:
        """Every board session cookie and CSRF token any context has shown, for redaction from evidence.

        Values accumulate across calls, so a session that later ends (sign-out,
        revocation) is still redacted from what was recorded while it was live.
        """

        contexts = [(self.context, self.page)] + [(viewer.context, viewer.page) for viewer in self.viewers]
        for context, page in contexts:
            try:
                self._seen_secrets.update(cookie["value"] for cookie in context.cookies() if cookie["name"].startswith("prism_board_"))
                csrf = page.evaluate("() => (typeof state === 'object' && state && state.boardCsrf) || ''")
                if csrf:
                    self._seen_secrets.add(csrf)
            except Exception:
                pass
        return [value for value in self._seen_secrets if isinstance(value, str) and len(value) >= 16]

    def start_trace(self, context: Any = None) -> None:
        """Start tracing after sign-in so the trace never records the token typed into the form."""

        target = context if context is not None else self.context
        target.tracing.start(screenshots=True, snapshots=True, sources=False)
        for viewer in self.viewers:
            if viewer.context is target:
                viewer.traced = True
