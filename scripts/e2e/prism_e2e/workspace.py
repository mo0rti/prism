"""Setup and state: wheel, venv, disposable workspace, grants, the board, fixtures and checks.

Everything runs against a wheel installed in a fresh virtual environment and a
disposable workspace under the run's ``work`` folder; the maintainer
repository is only read (its sources are copied to build the wheel).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import config
from .procs import clean_env, run_captured, start_background, stop_background
from .tokens import TokenRegistry

PROJECT_NAME = "Doc review"
APP = "backend"
JOURNEY_FOLDERS = (
    "knowledge/wiki/features",
    "knowledge/wiki/personas",
    "knowledge/wiki/app-requirements",
    "knowledge/wiki/business-rules",
    "knowledge/wiki/design",
    "knowledge/wiki/technical-design",
    "knowledge/wiki/api-contracts",
    "knowledge/wiki/decisions",
    "knowledge/wiki/releases",
)
KEEP_NAMES = {"_FORMAT.md", ".gitkeep"}
PENDING_INTAKE = "knowledge/intake/pending/2026-09-30-review-summary"
PROCESSED_BRIEF = "knowledge/intake/processed/2026-09-30-review-summary/brief.md"


class SetupError(RuntimeError):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path, log: list[str], what: str, timeout: float = 900) -> str:
    result = run_captured(command, cwd=cwd, env=clean_env(), timeout=timeout)
    log.append(f"$ {' '.join(command)}\n{result.stdout}{result.stderr}".rstrip())
    if result.timed_out or result.exit_code != 0:
        tail = (result.stdout + result.stderr).strip()[-600:]
        raise SetupError(f"{what} failed (exit {result.exit_code}, timed out {result.timed_out}): {tail}")
    return result.stdout


# --- wheel, venv, workspace ----------------------------------------------------------


def build_wheel(repo_root: Path, work: Path, log: list[str]) -> Path:
    """Build a wheel from a copy of the current tree, so the repository gets no build or egg-info folders."""

    source = work / "wheel-src"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir(parents=True)
    shutil.copytree(repo_root / "prism_cli", source / "prism_cli", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "MANIFEST.in", "README.md"):
        shutil.copy2(repo_root / name, source / name)
    wheelhouse = work / "wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if uv:
        _run([uv, "build", "--wheel", "--out-dir", str(wheelhouse)], cwd=source, log=log, what="Building the wheel with uv")
    else:
        _run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheelhouse), "."], cwd=source, log=log, what="Building the wheel with pip")
    wheels = sorted(wheelhouse.glob("prism_kit-*.whl"))
    if len(wheels) != 1:
        raise SetupError(f"Expected exactly one built wheel, found {len(wheels)}.")
    return wheels[0]


@dataclass
class Environment:
    """The installed product and its disposable workspace."""

    venv: Path
    workspace: Path
    wheel: Path
    wheel_sha256: str

    @property
    def python(self) -> Path:
        return self.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @property
    def prism(self) -> Path:
        return self.venv / ("Scripts/prism.exe" if os.name == "nt" else "bin/prism")


def create_environment(wheel: Path, work: Path, log: list[str]) -> Environment:
    venv = work / "venv"
    _run([sys.executable, "-m", "venv", str(venv)], cwd=work, log=log, what="Creating the virtual environment")
    env = Environment(venv=venv, workspace=work / "ws", wheel=wheel, wheel_sha256=sha256_of(wheel))
    uv = shutil.which("uv")
    if uv:
        _run([uv, "pip", "install", "--python", str(env.python), str(wheel)], cwd=work, log=log, what="Installing the wheel with uv")
    else:
        _run([str(env.python), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], cwd=work, log=log, what="Installing the wheel with pip")
    return env


def install_workspace(env: Environment, log: list[str]) -> None:
    env.workspace.mkdir(parents=True, exist_ok=True)
    _run(
        [str(env.prism), "workflow", "install", ".", "--name", PROJECT_NAME, "--app", APP, "--apply", "--yes"],
        cwd=env.workspace,
        log=log,
        what="Installing the workflow into the workspace",
    )


def prism_version(env: Environment) -> str:
    result = run_captured([str(env.python), "-c", "import importlib.metadata as m; print(m.version('prism-kit'))"], cwd=env.venv.parent, env=clean_env(), timeout=60)
    return result.stdout.strip() or "unknown"


def issue_grant(env: Environment, tokens: TokenRegistry, label: str, name: str, kind: str, log: list[str]) -> str:
    """Create one writable participant. Returns its participant ID; the token goes only into the registry."""

    command = [str(env.prism), "board", "grant", name, "--path", ".", "--kind", kind, "--write"]
    result = run_captured(command, cwd=env.workspace, env=clean_env(), timeout=120)
    if result.exit_code != 0:
        raise SetupError(f"Issuing the grant for {name} failed (exit {result.exit_code}).")
    data = json.loads(result.stdout)
    tokens.add(label, data["token"])
    shown = dict(data, token=f"<REDACTED-TOKEN length={len(data['token'])}>")
    log.append(f"$ prism board grant \"{name}\" --path . --kind {kind} --write\n{json.dumps(shown, indent=2)}")
    return data["participant"]["participant_id"]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class Board:
    env: Environment
    output: Path
    port: int = 0
    process: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout_s: float = 60.0) -> None:
        self.port = free_port()
        command = [str(self.env.prism), "board", "serve", ".", "--port", str(self.port), "--no-open"]
        self.process = start_background(command, cwd=self.env.workspace, env=clean_env(), output=self.output)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise SetupError(f"The board exited at start with code {self.process.returncode}: {self.output.read_text(encoding='utf-8', errors='replace')[-400:]}")
            try:
                with urllib.request.urlopen(self.base_url + "/", timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                time.sleep(0.25)
        raise SetupError("The board did not answer within 60 seconds.")

    def stop(self) -> str:
        if self.process is None:
            return "not started"
        return stop_background(self.process)


# --- journey files and fixtures ----------------------------------------------------------


def place_pending_brief(workspace: Path, fixture_set: Path | None = None) -> None:
    """The input of ``po-intake``: the review-summary brief, in the pending intake folder."""

    source = config.FIXTURES_DIR / "po-intake" / PROCESSED_BRIEF
    if fixture_set is not None and (fixture_set / "po-intake" / PROCESSED_BRIEF).is_file():
        source = fixture_set / "po-intake" / PROCESSED_BRIEF
    target = workspace / PENDING_INTAKE / "brief.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def reset_journey_files(workspace: Path) -> None:
    """Remove everything a journey step wrote, keeping the installed templates."""

    for folder in JOURNEY_FOLDERS:
        base = workspace / folder
        if not base.is_dir():
            continue
        for path in base.iterdir():
            if path.name in KEEP_NAMES:
                continue
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    processed = workspace / "knowledge/intake/processed"
    if processed.is_dir():
        for path in processed.iterdir():
            if path.name not in KEEP_NAMES:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
    pending = workspace / PENDING_INTAKE
    if pending.exists():
        shutil.rmtree(pending)


def fixture_steps_through(step: str | None) -> list[str]:
    """Steps whose fixture deltas build the state after ``step`` (``None``: the baseline, no deltas)."""

    if step is None:
        return []
    return list(config.STEP_IDS[: config.STEP_IDS.index(step) + 1])


def fixture_files(steps: list[str], fixture_set: Path | None = None) -> dict[str, Path]:
    """Relative path to fixture file for the cumulative state; a later step's file replaces an earlier one's.

    A fixture set overlays the default fixtures: within a step, the set's file replaces the default file of the same path.
    """

    files: dict[str, Path] = {}
    for step in steps:
        roots = [config.FIXTURES_DIR / step]
        if fixture_set is not None:
            roots.append(fixture_set / step)
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    files[path.relative_to(root).as_posix()] = path
    return files


_ROW = re.compile(r"^\|\s*F-\d+\s*\|")


def rewrite_status_board(board_text: str, row: str | None) -> str:
    """The status board with its feature table holding only ``row`` (or no row)."""

    lines = board_text.split("\n")
    out: list[str] = []
    inserted = False
    for line in lines:
        if _ROW.match(line):
            continue
        out.append(line)
        if row is not None and not inserted and line.startswith("|----"):
            out.append(row)
            inserted = True
    return "\n".join(out)


_OPERATIONS_HEADING = "## Operations"
_OPERATIONS_TABLE = (
    "| App | Delivery target | Released features | Latest release | Latest attempt outcome | Open bugs | Open incidents |\n"
    "|-----|-----------------|-------------------|----------------|------------------------|-----------|----------------|"
)
_RELEASE_FILE = re.compile(r"^REL-(\d+)\.md$")


def operations_rows(workspace: Path, stages: str) -> list[str]:
    """The ``## Operations`` rows of the journey: one per app that has a released feature or a release record.

    ``stages`` is the feature's ``App stages`` cell. The latest release of an app is the highest-numbered record that names it,
    and the outcome is the one its first Delivery row for the app carries. The journey has no bugs or incidents.
    """

    released = {app.strip() for app, _separator, stage in (part.partition(":") for part in stages.split(";")) if stage.strip() == "released"}
    latest: dict[str, tuple[int, str, str]] = {}
    folder = workspace / "knowledge/wiki/releases"
    for path in sorted(folder.glob("REL-*.md")) if folder.is_dir() else []:
        match = _RELEASE_FILE.match(path.name)
        if not match:
            continue
        number = int(match.group(1))
        seen: set[str] = set()
        for cells in _rows_of(path.read_text(encoding="utf-8"), "Delivery"):
            if cells[0] == "Item" or len(cells) < 6 or cells[1] in seen:
                continue
            seen.add(cells[1])
            if cells[1] not in latest or latest[cells[1]][0] < number:
                latest[cells[1]] = (number, cells[2], cells[5])
    rows = []
    for app in sorted(released | set(latest)):
        number, target, outcome = latest.get(app, (0, _EM_DASH, _EM_DASH))
        record = f"REL-{number:03d}" if number else _EM_DASH
        features = config.FEATURE_ID if app in released else _EM_DASH
        rows.append(f"| {app} | {target} | {features} | {record} | {outcome} | {_EM_DASH} | {_EM_DASH} |")
    return rows


def rewrite_operations(board_text: str, rows: list[str]) -> str:
    """The status board with the rows of its ``## Operations`` table replaced by ``rows``; a board without the table gains it when there are rows."""

    if rows and _OPERATIONS_HEADING not in board_text.split("\n"):
        return board_text.rstrip("\n") + f"\n\n{_OPERATIONS_HEADING}\n\n{_OPERATIONS_TABLE}\n" + "\n".join(rows) + "\n"
    out: list[str] = []
    in_section = False
    after_separator = False
    for line in board_text.split("\n"):
        if line.strip() == _OPERATIONS_HEADING:
            in_section = True
        elif in_section and after_separator and line.startswith("|"):
            continue
        out.append(line)
        if in_section and not after_separator and line.startswith("|-"):
            out.extend(rows)
            after_separator = True
    return "\n".join(out)


_IN_DEV_AND_LATER = ("in-dev", "ready-for-qa", "in-qa", "ready-for-release", "released")
_SECTION = r"(?ms)^## {name}\s*\n(.*?)(?=^## |\Z)"
_EM_DASH = "\u2014"


def feature_apps(text: str) -> list[str]:
    """The app IDs of a feature page's ``apps`` front matter, as a flow list or a block list."""

    lines = text.split("\n")
    for index, line in enumerate(lines):
        flow = re.match(r"^apps:\s*\[(.*)\]\s*$", line)
        if flow:
            return [item.strip() for item in flow.group(1).split(",") if item.strip()]
        if line.strip() == "apps:":
            apps = []
            for item in lines[index + 1:]:
                block = re.match(r"^-\s+(\S+)\s*$", item)
                if not block:
                    break
                apps.append(block.group(1))
            return apps
    return []


def _rows_of(text: str, name: str) -> list[list[str]]:
    """The data rows of a table section, each as its cells; the header and the separator are left out."""

    section = re.search(_SECTION.format(name=name), text)
    rows = []
    for line in section.group(1).split("\n") if section else []:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
        if cells and not set(cells[0]) <= set("-: ") and cells[0] not in {"App", "Row"}:
            rows.append(cells)
    return rows


def app_stages_cell(front_matter: dict[str, str], text: str) -> str:
    """The ``App stages`` cell of the journey: the stage of each app, from the rows of its evidence tables.

    ``in-dev`` without a Delivery evidence row, ``ready-for-qa`` with one, ``in-qa`` once a QA row names the app,
    ``ready-for-release`` with a pending Release row and ``released`` when its Release row says so.
    """

    if front_matter.get("status") not in _IN_DEV_AND_LATER:
        return _EM_DASH
    delivered = {cells[0] for cells in _rows_of(text, "Delivery evidence")}
    tested = {cells[0] for cells in _rows_of(text, "QA verification")}
    release = {cells[0]: cells[4] for cells in _rows_of(text, "Release") if len(cells) > 4}
    stages = []
    for app in feature_apps(text):
        if release.get(app) == "released":
            stage = "released"
        elif app in release:
            stage = "ready-for-release"
        elif app in tested:
            stage = "in-qa"
        else:
            stage = "ready-for-qa" if app in delivered else "in-dev"
        stages.append(f"{app}: {stage}")
    return "; ".join(stages) or _EM_DASH


def design_tracks_cell(text: str) -> str:
    """The ``Design tracks`` cell of the journey: ``ui: <state>; technical: <state>`` from the page's ``design-tracks`` block, else ``—``."""

    block = re.search(r"(?m)^design-tracks:\s*\n((?:[ \t]+\S.*\n)+)", text)
    if not block:
        return "—"
    states = dict(re.findall(r"(?m)^[ \t]+(ui|technical):\s*(\S+)\s*$", block.group(1)))
    return f"ui: {states['ui']}; technical: {states['technical']}" if "ui" in states and "technical" in states else "—"


def feature_row(front_matter: dict[str, str], text: str = "") -> str:
    return "| {id} | {title} | {status} | {owner} | {review} | {tracks} | {stages} | — |".format(
        tracks=design_tracks_cell(text),
        id=front_matter["id"],
        title=front_matter["title"],
        status=front_matter["status"],
        owner=front_matter["owner"],
        review=front_matter.get("advisory-review", "not-needed"),
        stages=app_stages_cell(front_matter, text),
    )


def seed_state(workspace: Path, step: str | None, fixture_set: Path | None = None) -> list[str]:
    """Rebuild the journey state after ``step`` from the recorded fixtures. Returns the files written.

    The feature's row in the status board is rebuilt too. The general index is not: it gains a line for
    each page when the board writes that page, so a seeded page has no line until its step runs, and lint
    reports that as a warning.
    """

    reset_journey_files(workspace)
    files = fixture_files(fixture_steps_through(step), fixture_set)
    for relative, source in files.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    board_path = workspace / "knowledge/wiki/status-board.md"
    feature = find_feature_page(workspace)
    page_text = feature.read_text(encoding="utf-8") if feature else ""
    row = feature_row(parse_front_matter(page_text), page_text) if feature else None
    board = rewrite_status_board(board_path.read_text(encoding="utf-8"), row)
    stages = app_stages_cell(parse_front_matter(page_text), page_text) if feature else _EM_DASH
    board_path.write_text(rewrite_operations(board, operations_rows(workspace, stages)), encoding="utf-8", newline="\n")
    return sorted(files)


# --- reading the workspace for the checks -------------------------------------------------


def find_feature_page(workspace: Path, feature_id: str = config.FEATURE_ID) -> Path | None:
    pages = sorted((workspace / "knowledge/wiki/features").glob(f"{feature_id}-*.md"))
    return pages[0] if pages else None


def parse_front_matter(text: str) -> dict[str, str]:
    """Flat ``key: value`` pairs of a page's front matter. List values are kept as their raw text."""

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if match:
            data[match.group(1)] = match.group(2).strip().strip("'\"")
    return data


@dataclass
class Question:
    number: str
    text: str
    owner: str
    status: str

    @property
    def is_open(self) -> bool:
        return self.status.strip().lower() == "open"


def parse_questions(text: str) -> list[Question]:
    """Rows of the ``## Open questions`` table."""

    questions: list[Question] = []
    in_section = False
    for line in text.split("\n"):
        if line.startswith("## "):
            in_section = line.strip().lower() == "## open questions"
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        questions.append(Question(cells[0], cells[1], cells[2], "|".join(cells[3:])))
    return questions


@dataclass
class FeatureState:
    status: str
    owner: str
    board_status: str | None
    board_owner: str | None
    questions: list[Question]
    text: str

    def open_questions(self, owner: str) -> list[Question]:
        return [question for question in self.questions if question.is_open and question.owner == owner]


def read_feature(workspace: Path, feature_id: str = config.FEATURE_ID) -> FeatureState | None:
    page = find_feature_page(workspace, feature_id)
    if page is None:
        return None
    text = page.read_text(encoding="utf-8")
    front = parse_front_matter(text)
    board_status = board_owner = None
    board_path = workspace / "knowledge/wiki/status-board.md"
    if board_path.is_file():
        for line in board_path.read_text(encoding="utf-8").split("\n"):
            if _ROW.match(line) and line.split("|")[1].strip() == feature_id:
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if len(cells) >= 4:
                    board_status, board_owner = cells[2], cells[3]
    return FeatureState(front.get("status", ""), front.get("owner", ""), board_status, board_owner, parse_questions(text), text)


def api_surface_section(text: str) -> str:
    """The text under a feature page's ``## API surface`` heading."""

    lines = text.split("\n")
    for index, line in enumerate(lines):
        if re.match(r"^##\s+API surface\s*#*\s*$", line.rstrip("\r")):
            end = next((offset for offset in range(index + 1, len(lines)) if lines[offset].startswith("## ")), len(lines))
            return "\n".join(lines[index + 1:end])
    return ""


_NO_API_SURFACE = frozenset(
    {"none", "no api", "not applicable", "n/a", "no api changes", "no api changes identified", "no api changes required", "no api surface"}
)


def declares_api_work(text: str) -> bool:
    """Whether a feature page's API surface declares API work (the rule the board and lint apply)."""

    normalized = re.sub(r"\s+", " ", api_surface_section(text)).strip().lower().rstrip(".").strip()
    return bool(normalized) and normalized not in _NO_API_SURFACE


def design_tracks(text: str) -> dict[str, str]:
    """The `ui` and `technical` states of a feature page's `design-tracks` front matter (empty when it has none)."""

    states: dict[str, str] = {}
    lines = text.split(chr(10))
    in_tracks = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("design-tracks:"):
            in_tracks = True
            continue
        if in_tracks and line[:1] not in {" ", chr(9)}:
            in_tracks = False
        match = re.match(r"^\s+(ui|technical):\s*(.*)$", line) if in_tracks else None
        if match:
            states[match.group(1)] = match.group(2).strip()
    return states


def find_technical_design(workspace: Path, feature_id: str = config.FEATURE_ID) -> Path | None:
    pages = sorted((workspace / "knowledge/wiki/technical-design").glob(f"{feature_id}-*.md"))
    return pages[0] if pages else None


API_CONTRACT = "knowledge/wiki/api-contracts/F-001.md"
REQUIREMENT = "knowledge/wiki/app-requirements/F-001-backend.md"


def read_api_contract(workspace: Path) -> dict[str, str] | None:
    """Front matter of the feature's API contract page, or ``None`` when there is none."""

    page = workspace / API_CONTRACT
    return parse_front_matter(page.read_text(encoding="utf-8")) if page.is_file() else None


# The design handoff leaves the developer's question open on purpose; lint reports it as an error
# until dev-clarify answers it. These are the only error codes a step may leave behind.
ALLOWED_LINT_CODES: dict[str, frozenset[str]] = {
    "design-handoff": frozenset({"unresolved-open-questions"}),
}


@dataclass
class LintResult:
    errors: int
    warnings: int
    exit_code: int
    error_codes: list[str] = field(default_factory=list)

    def unexpected(self, allowed: frozenset[str] = frozenset()) -> bool:
        """True when lint could not run, or reported an error outside ``allowed``."""

        return self.errors < 0 or any(code not in allowed for code in self.error_codes) or (self.errors > 0 and not self.error_codes)


def run_lint(env: Environment) -> LintResult:
    result = run_captured([str(env.prism), "wiki", "lint", ".", "--json"], cwd=env.workspace, env=clean_env(), timeout=120)
    try:
        data = json.loads(result.stdout)
        facts = data["facts"]
        codes = [str(item.get("code")) for item in data.get("diagnostics", []) if item.get("severity") == "error"]
        return LintResult(int(facts["error_count"]), int(facts["warning_count"]), result.exit_code or 0, codes)
    except (ValueError, KeyError, TypeError):
        return LintResult(-1, -1, result.exit_code if result.exit_code is not None else -1)


def fetch_receipt(board: Board, token: str, operation_id: str) -> dict:
    """The operation receipt, read through the board's HTTP API with a participant's Bearer token."""

    request = urllib.request.Request(f"{board.base_url}/api/board/v1/operations/{operation_id}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")[:300]
        return {"error": f"HTTP {error.code}", "detail": body}
    except (urllib.error.URLError, OSError, ValueError) as error:
        return {"error": type(error).__name__, "detail": str(error)}
