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
    "knowledge/wiki/bugs",
    "knowledge/wiki/incidents",
)
KEEP_NAMES = {"_FORMAT.md", ".gitkeep"}
PENDING_INTAKE = "knowledge/intake/pending/2026-09-30-review-summary"
PROCESSED_BRIEF = "knowledge/intake/processed/2026-09-30-review-summary/brief.md"
# The steps that process a pending intake folder: the folder, and the file the step finds in it. The fixtures hold the
# file under the processed path the step leaves it at; the runner copies it back to the pending folder before the step runs.
PENDING_INPUTS: dict[str, tuple[str, str]] = {
    "po-intake": ("2026-09-30-review-summary", "brief.md"),
    "ingest-incident": ("2026-10-09-release-incident", "report.md"),
}


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


def issue_grant(env: Environment, tokens: TokenRegistry, label: str, name: str, kind: str, log: list[str], roles: tuple[str, ...] = ()) -> str:
    """Create one writable participant, holding exactly ``roles`` (a human grant only). Returns its participant ID; the token goes only into the registry."""

    command = [str(env.prism), "board", "grant", name, "--path", ".", "--kind", kind, "--write"]
    if roles:
        command += ["--role", ",".join(roles)]
    result = run_captured(command, cwd=env.workspace, env=clean_env(), timeout=120)
    if result.exit_code != 0:
        raise SetupError(f"Issuing the grant for {name} failed (exit {result.exit_code}): {(result.stderr or result.stdout).strip()[-300:]}")
    data = json.loads(result.stdout)
    tokens.add(label, data["token"])
    shown = dict(data, token=f"<REDACTED-TOKEN length={len(data['token'])}>")
    role_flag = f" --role {','.join(roles)}" if roles else ""
    log.append(f"$ prism board grant \"{name}\" --path . --kind {kind} --write{role_flag}\n{json.dumps(shown, indent=2)}")
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


def pending_folder(step_id: str) -> str:
    """The pending intake folder (relative to the workspace) that a step processes."""

    return f"knowledge/intake/pending/{PENDING_INPUTS[step_id][0]}"


def place_pending_input(workspace: Path, step_id: str, fixture_set: Path | None = None) -> Path:
    """The input of an ingest step, in the pending intake folder: the file its fixtures hold under the processed path."""

    folder, name = PENDING_INPUTS[step_id]
    processed = f"knowledge/intake/processed/{folder}/{name}"
    source = config.FIXTURES_DIR / step_id / processed
    if fixture_set is not None and (fixture_set / step_id / processed).is_file():
        source = fixture_set / step_id / processed
    target = workspace / pending_folder(step_id) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def place_pending_brief(workspace: Path, fixture_set: Path | None = None) -> None:
    """The input of ``po-intake``: the review-summary brief, in the pending intake folder."""

    place_pending_input(workspace, "po-intake", fixture_set)


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
    for step_id in PENDING_INPUTS:
        pending = workspace / pending_folder(step_id)
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


_ACTIVE_BUG_STATUSES = ("open", "in-fix", "fixed", "verified")
_BUGS_HEADING = "## Bugs"
_BUGS_TABLE = (
    "| ID | Bug | Status | Owner | Apps | Feature | Blocking |\n"
    "|----|-----|--------|-------|------|---------|----------|"
)
_BUG_KEYS = ("id", "title", "status", "owner", "apps", "feature", "blocking")
_NUMBER_AT_END = re.compile(r"(\d+)$")


def _flow_list(raw: str) -> list[str]:
    """The items of a front matter flow list such as ``[backend, worker]``; a bare value is one item."""

    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip("'\"") for item in text.split(",") if item.strip()]


def _id_order(identifier: str) -> tuple[int, str]:
    match = _NUMBER_AT_END.search(identifier)
    return (int(match.group(1)) if match else 10**9, identifier)


def _ids_text(identifiers: list[str]) -> str:
    ordered = sorted(dict.fromkeys(identifiers), key=_id_order)
    return ", ".join(ordered) if ordered else _EM_DASH


def bug_rows(workspace: Path) -> list[dict[str, str]]:
    """The ``## Bugs`` rows of the journey: every bug page that is not ``released`` or ``closed``, in number order."""

    folder = workspace / "knowledge/wiki/bugs"
    rows = []
    for path in sorted(folder.glob("BUG-*.md")) if folder.is_dir() else []:
        front = parse_front_matter(path.read_text(encoding="utf-8"))
        if front.get("status") not in _ACTIVE_BUG_STATUSES:
            continue
        rows.append(
            {
                "id": front["id"],
                "title": re.sub(r"\s+", " ", front.get("title", "")).strip().replace("|", "&#124;"),
                "status": front["status"],
                "owner": front.get("owner", _EM_DASH),
                "apps": ", ".join(_flow_list(front.get("apps", ""))) or _EM_DASH,
                "feature": front.get("feature", "none"),
                "blocking": "yes" if front.get("blocking", "").strip().lower() == "true" else "no",
            }
        )
    return sorted(rows, key=lambda row: _id_order(row["id"]))


def format_bug_row(row: dict[str, str]) -> str:
    return "| " + " | ".join(row[key] for key in _BUG_KEYS) + " |"


def open_incidents(workspace: Path) -> list[tuple[str, list[str]]]:
    """The incidents that are not ``resolved``, each as its ID and the apps it names."""

    folder = workspace / "knowledge/wiki/incidents"
    found = []
    for path in sorted(folder.glob("INC-*.md")) if folder.is_dir() else []:
        front = parse_front_matter(path.read_text(encoding="utf-8"))
        if front.get("status") in {"open", "mitigated"}:
            found.append((front["id"], _flow_list(front.get("apps", ""))))
    return found


def open_bugs_cell(workspace: Path, feature_id: str = config.FEATURE_ID) -> str:
    """The ``Open bugs`` cell of a feature's row: the active bugs linked to it."""

    return _ids_text([row["id"] for row in bug_rows(workspace) if row["feature"].casefold() == feature_id.casefold()])


def operations_rows(workspace: Path, stages: str) -> list[str]:
    """The ``## Operations`` rows of the journey: one per app that has a released feature, a release record, an open bug or an open incident.

    ``stages`` is the feature's ``App stages`` cell. The latest release of an app is the highest-numbered record that names it,
    and the outcome is the one its first Delivery row for the app carries. The open bugs and incidents are those that name the app.
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
    bugs = bug_rows(workspace)
    incidents = open_incidents(workspace)
    apps = released | set(latest) | {app for row in bugs for app in _flow_list(row["apps"])} | {app for _id, named in incidents for app in named}
    rows = []
    for app in sorted(apps, key=str.casefold):
        number, target, outcome = latest.get(app, (0, _EM_DASH, _EM_DASH))
        record = f"REL-{number:03d}" if number else _EM_DASH
        features = config.FEATURE_ID if app in released else _EM_DASH
        open_bugs = _ids_text([row["id"] for row in bugs if app in _flow_list(row["apps"])])
        open_incident_ids = _ids_text([identifier for identifier, named in incidents if app in named])
        rows.append(f"| {app} | {target} | {features} | {record} | {outcome} | {open_bugs} | {open_incident_ids} |")
    return rows


def _rewrite_table(board_text: str, heading: str, table: str, rows: list[str]) -> str:
    """The status board with the rows of the table under ``heading`` replaced by ``rows``; a board without the table gains it when there are rows."""

    if rows and heading not in board_text.split("\n"):
        return board_text.rstrip("\n") + f"\n\n{heading}\n\n{table}\n" + "\n".join(rows) + "\n"
    out: list[str] = []
    in_section = False
    after_separator = False
    for line in board_text.split("\n"):
        if line.strip() == heading:
            in_section = True
        elif line.startswith("## "):
            in_section = False  # another table follows; its rows are not this table's
        elif in_section and after_separator and line.startswith("|"):
            continue
        out.append(line)
        if in_section and not after_separator and line.startswith("|-"):
            out.extend(rows)
            after_separator = True
    return "\n".join(out)


def rewrite_operations(board_text: str, rows: list[str]) -> str:
    """The status board with the rows of its ``## Operations`` table replaced by ``rows``; a board without the table gains it when there are rows."""

    return _rewrite_table(board_text, _OPERATIONS_HEADING, _OPERATIONS_TABLE, rows)


def rewrite_bugs(board_text: str, rows: list[str]) -> str:
    """The status board with the rows of its ``## Bugs`` table replaced by ``rows``; a board without the table gains it when there are rows."""

    return _rewrite_table(board_text, _BUGS_HEADING, _BUGS_TABLE, rows)


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


def feature_row(front_matter: dict[str, str], text: str = "", open_bugs: str = _EM_DASH) -> str:
    return "| {id} | {title} | {status} | {owner} | {review} | {tracks} | {stages} | {bugs} |".format(
        bugs=open_bugs,
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
    row = feature_row(parse_front_matter(page_text), page_text, open_bugs_cell(workspace)) if feature else None
    board = rewrite_status_board(board_path.read_text(encoding="utf-8"), row)
    board = rewrite_bugs(board, [format_bug_row(bug) for bug in bug_rows(workspace)])
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


BUG_ID = "BUG-001"
INCIDENT_ID = "INC-001"
STATUS_BOARD = "knowledge/wiki/status-board.md"


@dataclass
class Page:
    """A wiki page read for a check: its flat front matter and its text."""

    path: Path
    front: dict[str, str]
    text: str

    def section(self, name: str) -> str:
        """The text under a ``## name`` heading, without the heading."""

        match = re.search(_SECTION.format(name=re.escape(name)), self.text)
        return match.group(1) if match else ""

    def rows(self, name: str) -> list[list[str]]:
        """The data rows of a table section, each as its cells."""

        return _rows_of(self.text, name)

    def front_list(self, key: str) -> list[str]:
        """The items of a front matter list, written as a flow list (``[a, b]``) or as a block list; empty when the key is absent."""

        lines = self.text.split("\n")
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                break
            match = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
            if not match:
                continue
            if match.group(1).strip():
                return _flow_list(match.group(1))
            items = []
            for item in lines[index + 1:]:
                block = re.match(r"^\s*-\s+(.*)$", item)
                if not block:
                    break
                items.append(block.group(1).strip().strip("'\""))
            return items
        return []


def read_page(workspace: Path, folder: str, prefix: str) -> Page | None:
    """The first page of ``knowledge/wiki/<folder>/`` whose file name starts with ``prefix`` (``BUG-001``, ``REL-002``), or ``None``."""

    pages = sorted((workspace / "knowledge/wiki" / folder).glob(f"{prefix}*.md"))
    if not pages:
        return None
    text = pages[0].read_text(encoding="utf-8")
    return Page(pages[0], parse_front_matter(text), text)


def read_requirement(workspace: Path) -> Page | None:
    page = workspace / REQUIREMENT
    if not page.is_file():
        return None
    text = page.read_text(encoding="utf-8")
    return Page(page, parse_front_matter(text), text)


def criterion_numbers(text: str) -> list[int]:
    """The numbers of the acceptance criteria listed in a feature page (``AC-3`` is 3), in order."""

    section = re.search(_SECTION.format(name="Acceptance criteria"), text)
    return [int(number) for number in re.findall(r"(?m)^[-*]\s*\[[ xX]\]\s*(?:\*\*\w+:\*\*\s*)?AC-(\d+)\b", section.group(1))] if section else []


def criterion_text(text: str, number: int) -> str:
    """The text of acceptance criterion ``AC-<number>`` in a feature page, or an empty string when the page has none."""

    section = re.search(_SECTION.format(name="Acceptance criteria"), text)
    match = re.search(r"(?m)^[-*]\s*\[[ xX]\]\s*(?:\*\*\w+:\*\*\s*)?AC-" + str(number) + r"\b(.*)$", section.group(1)) if section else None
    return match.group(1).strip() if match else ""


def cited_numbers(cell: str) -> set[int]:
    """The criterion numbers a QA row's Criteria cell cites (``AC-1@v1:...`` is 1)."""

    return {int(number) for number in re.findall(r"\bAC-(\d+)@", cell)}


def board_row_cells(workspace: Path, table_heading: str, key: str) -> list[str] | None:
    """The cells of the status board row of ``key`` (a bug ID or an app) under ``## table_heading``, or ``None``."""

    board = workspace / STATUS_BOARD
    if not board.is_file():
        return None
    in_section = False
    for line in board.read_text(encoding="utf-8").split("\n"):
        if line.startswith("## "):
            in_section = line.strip() == f"## {table_heading}"
            continue
        if in_section and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and cells[0] == key:
                return cells
    return None


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
