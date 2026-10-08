"""Shared fixtures for the QA and bug tests: a two-app board walked through the service to `ready-for-qa`.

`QaBoard` is a base class without tests of its own. `backend` and `worker` (an `other` stack app) are the two apps of
feature F-001, whose criteria are AC-1 for `backend`, AC-2 for `worker` and AC-3 for both together (an integration).
Every step before QA goes through the board service, so the provenance journal knows who produced each delivery row.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import yaml

from prism_cli.board_service import BoardError, BoardService, _parse_markdown
from prism_cli.wiki_model import criterion_revision, read_feature_evidence
from tests.board_approval import apply_preview, human_with_roles
from tests.wiki_files import refresh_status_board
from tests.test_board_service import (
    _journey_requirement_page,
    _read_revisions,
    _replace_body_section_text,
    _set_feature_stage,
    _set_requirement_status,
)
from tests.qa_pages import (  # noqa: F401
    FIX_HEADER,
    VERIFICATION_HEADER,
    append_history,
    bug_page,
    fix_row,
    history_entry,
    requirement_path,
    verification_row,
)
from tests.test_lifecycle_model import (
    DELIVERY_HEADER,
    FEATURE,
    QA_HEADER,
    RELEASE_HEADER,
    _Workspace,
    delivery_row,
    table,
)

TEXT_BACKEND = "A reviewer can record the outcome of a backend review."
TEXT_WORKER = "A saved summary is produced by the worker."
TEXT_BOTH = "A summary recorded by the backend is exported by the worker."
BOTH = ["backend", "worker"]
SETTINGS = "knowledge/wiki/SETTINGS.md"
BUGS = "knowledge/wiki/bugs"


def ref(number: int, apps: list[str], text: str, *, integration: bool = False) -> str:
    return f"AC-{number}@{criterion_revision('F-001', number, apps, integration, '', text)}"


AC1 = ref(1, ["backend"], TEXT_BACKEND)
AC2 = ref(2, ["worker"], TEXT_WORKER)
AC3 = ref(3, BOTH, TEXT_BOTH, integration=True)


def qa_row(key: str, refs: list[str], artifacts: str, *, attempt: int = 1, result: str = "pass", environment: str = "ci", method: str = "automated") -> str:
    return f"| {key} | {', '.join(refs)} | {method} | {artifacts} | {environment} | qa-{attempt} | {result} | [run](https://ci.example/qa) | checked |"


def app_row(app: str, refs: list[str] | None = None, **kwargs: object) -> str:
    chosen = refs if refs is not None else [AC1] if app == "backend" else [AC2]
    return qa_row(app, chosen, f"`build:{app}#1`", **kwargs)  # type: ignore[arg-type]


def integration_row(**kwargs: object) -> str:
    return qa_row("integration:backend+worker", [AC3], "backend=`build:backend#1`; worker=`build:worker#1`", **kwargs)  # type: ignore[arg-type]


def release_row(app: str, attempt: int = 1, artifact: str | None = None) -> str:
    return f"| {app} | — | `{artifact or f'build:{app}#1'}` | release-{attempt} | pending | — | — |"


# The workspace after the walk to `ready-for-qa` and the tokens of its grants, built once and copied for every test.
_SNAPSHOT: dict[str, object] = {}
_ROLES = {"owner": ("Workflow owner", "po,designer,tech-lead,dev,qa,release"), "quinn": ("Quinn", "qa"), "devi": ("Devi", "dev,qa"), "pat": ("Pat", "po")}


def _cleanup_snapshot() -> None:
    folder = _SNAPSHOT.get("folder")
    if folder is not None:
        shutil.rmtree(str(folder), ignore_errors=True)


atexit.register(_cleanup_snapshot)


class QaBoard(_Workspace):
    """A board with feature F-001 at `ready-for-qa` (both apps delivered through the service) and humans for each role."""

    def setUp(self) -> None:
        if not _SNAPSHOT:
            self.build_snapshot()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace"
        shutil.copytree(str(_SNAPSHOT["root"]), self.root)
        self.start_service(dict(_SNAPSHOT["tokens"]))  # type: ignore[arg-type]

    def start_service(self, tokens: dict[str, str]) -> None:
        self.service = BoardService(self.root).start()
        self.addCleanup(self.service.close)
        self.agent = self.service.authenticate(tokens["agent"])
        # `owner` holds every role and delivers; the QA humans are separate grants.
        self.owner = self.service.authenticate(tokens["owner"], via_session=True)
        self.quinn = self.service.authenticate(tokens["quinn"], via_session=True)
        self.devi = self.service.authenticate(tokens["devi"], via_session=True)
        self.pat = self.service.authenticate(tokens["pat"], via_session=True)

    def build_snapshot(self) -> None:
        """Walk a board through the service to `ready-for-qa`, then keep a copy of the closed workspace."""

        super().setUp()
        criteria = [f"AC-1 [backend] {TEXT_BACKEND}", f"AC-2 [worker] {TEXT_WORKER}", f"AC-3 [integration: backend, worker] {TEXT_BOTH}"]
        self.seed(
            "raw",
            "po",
            self.page("raw", "po", BOTH, criteria, questions=["| 1 | Which details should the summary emphasize? | po | resolved: The key points. |"]),
        )
        service = BoardService(self.root).start()
        tokens = {"agent": service.create_participant("Workflow agent", "agent", True)["token"]}
        for key, (name, roles) in _ROLES.items():
            tokens[key] = service.create_participant(name, "human", True, roles=roles)["token"]
        service.close()
        self.start_service(tokens)
        self.walk_to_ready_for_qa()
        self.service.close()
        folder = tempfile.mkdtemp(prefix="prism-qa-snapshot-")
        shutil.copytree(str(self.root), Path(folder) / "workspace")
        _SNAPSHOT.update({"folder": folder, "root": str(Path(folder) / "workspace"), "tokens": tokens})
        self.start_service(tokens)

    # -- reading and previewing ---------------------------------------------------------------------------------------

    def read(self, relative: str) -> str:
        return self.service._read_text(self.root / relative)

    def put(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        if relative.startswith(("knowledge/wiki/bugs/", "knowledge/wiki/incidents/", "knowledge/wiki/releases/")):
            # A page planted straight into the wiki also changes the status board, which the service would have written.
            refresh_status_board(self.root)

    def feature(self) -> tuple[dict, str]:
        return _parse_markdown(self.read(FEATURE))

    def status(self) -> tuple[str, str]:
        frontmatter = self.feature()[0]
        return frontmatter["status"], frontmatter["owner"]

    def evidence(self):
        return read_feature_evidence(self.feature()[1])

    def propose(self, skill: str, changes: list[dict[str, str]]) -> dict:
        return self.service.preview_skill(self.agent, skill, changes, None, _read_revisions(self.service, self.agent, skill, changes))

    def ready(self, skill: str, changes: list[dict[str, str]]) -> dict:
        preview = self.propose(skill, changes)
        self.assertEqual("ready", preview["classification"], f"{skill}: {preview['checks']}")
        self.assertTrue(preview["applicable"], f"{skill}: {preview['blockers']}")
        return preview

    def apply(self, skill: str, changes: list[dict[str, str]], approver=None) -> dict:
        preview = self.ready(skill, changes)
        receipt = apply_preview(self.service, self.agent, preview, str(uuid4()), approver=approver or self.quinn)
        self.assertEqual("applied", receipt["state"], f"{skill}: {receipt}")
        return preview

    def refused(self, skill: str, changes: list[dict[str, str]], approver=None) -> BoardError:
        """The error of a proposal: at preview, or at apply by `approver` when the preview itself is accepted."""

        try:
            preview = self.propose(skill, changes)
        except BoardError as error:
            return error
        try:
            apply_preview(self.service, self.agent, preview, str(uuid4()), approver=approver or self.quinn)
        except BoardError as error:
            return error
        raise AssertionError(f"{skill} was applied; a refusal was expected: {preview['checks']}")

    # -- the walk to ready-for-qa -----------------------------------------------------------------------------------

    def step(self, skill: str, changes: list[dict[str, str]]) -> None:
        self.apply(skill, changes, approver=self.owner)

    def human_action(self, action: str) -> None:
        preview = self.service.preview_transition(self.owner, "F-001", action, {"semantic_review_acknowledged": True})
        self.assertTrue(preview["applicable"], preview["checks"])
        self.assertEqual("applied", apply_preview(self.service, self.owner, preview, str(uuid4()))["state"])

    def requirement(self, app: str, status: str) -> str:
        return _set_requirement_status(_journey_requirement_page("pending").replace("app: backend", f"app: {app}"), status)

    def deliver(self, app: str, status: str, owner: str, artifact: str | None = None) -> list[dict[str, str]]:
        current = self.read(FEATURE)
        body = _parse_markdown(current)[1]
        rows = [f"| {' | '.join(row.cells)} |" for row in read_feature_evidence(body).delivery]
        updated = _set_feature_stage(current, status, owner, self.service)
        updated = _replace_body_section_text(updated, "Delivery evidence", table(DELIVERY_HEADER, [*rows, delivery_row(app, artifact)]))
        path = f"knowledge/wiki/app-requirements/F-001-{app}.md"
        return [{"path": FEATURE, "content": updated}, {"path": path, "content": _set_requirement_status(self.read(path), "done")}]

    def walk_to_ready_for_qa(self) -> None:
        specified = _set_feature_stage(self.read(FEATURE), "specified", "po", self.service)
        self.step("po-specify", [{"path": FEATURE, "content": specified}])
        self.human_action("po-handoff")
        self.human_action("design-start")
        handed = _set_feature_stage(self.read(FEATURE), "ready-for-dev", "dev", self.service)
        self.step(
            "design-handoff",
            [
                {"path": FEATURE, "content": handed},
                {"path": "knowledge/wiki/app-requirements/F-001-backend.md", "content": self.requirement("backend", "pending")},
                {"path": "knowledge/wiki/app-requirements/F-001-worker.md", "content": self.requirement("worker", "pending")},
            ],
        )
        self.human_action("dev-start")
        self.step("dev-done", self.deliver("backend", "in-dev", "dev"))
        self.step("dev-done", self.deliver("worker", "ready-for-qa", "qa"))
        self.assertEqual(("ready-for-qa", "qa"), self.status())

    # -- editing the feature page -------------------------------------------------------------------------------------

    def with_section(self, heading: str, text: str, content: str | None = None) -> str:
        return _replace_body_section_text(content if content is not None else self.read(FEATURE), heading, text)

    def with_status(self, status: str, owner: str, content: str | None = None) -> str:
        return _set_feature_stage(content if content is not None else self.read(FEATURE), status, owner, self.service)

    def qa_table(self, rows: list[str], content: str | None = None) -> str:
        return self.with_section("QA verification", table(QA_HEADER, rows), content)

    def release_table(self, rows: list[str], content: str | None = None) -> str:
        return self.with_section("Release", table(RELEASE_HEADER, rows), content)

    def active_rows(self, section: str) -> list[str]:
        body = self.feature()[1]
        evidence = read_feature_evidence(body)
        rows = {"qa": evidence.qa, "delivery": evidence.delivery, "release": evidence.release}[section]
        return [f"| {' | '.join(row.cells)} |" for row in rows]

    def set_policy(self, separate: bool = True) -> None:
        text = f"---\nwiki-stale-after-days: 365\nqa-separate-from-dev: {'true' if separate else 'false'}\n---\n"
        self.put(SETTINGS, text)

    def frontmatter_with(self, content: str, **fields: object) -> str:
        frontmatter, body = _parse_markdown(content)
        frontmatter.update(fields)
        return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False).rstrip()}\n---\n{body}"
