"""Shared fixtures for the release tests: a two-app board walked through the service to `ready-for-release`.

`ReleaseBoard` is a base class without tests of its own. It extends `QaBoard`: feature F-001 with the apps `backend` and
`worker`, both delivered and passed through QA by the service, and `SETTINGS.md` declaring the delivery targets. The page
builders live in `tests/release_pages.py`; the board walks the real services, so every approval is a human in a session.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

from tests import qa_support
from tests.qa_pages import FIX_HEADER, VERIFICATION_HEADER, bug_page, fix_row, verification_row  # noqa: F401
from tests.qa_support import (
    BUGS,
    FEATURE,
    SETTINGS,
    QaBoard,
    app_row,
    integration_row,
    release_row as pending_row,
)
from tests.release_pages import (  # noqa: F401
    DELIVERY_HEADER,
    EVIDENCE,
    RELEASE_HEADER,
    RELEASES,
    delivery,
    record_id,
    record_page,
    record_path,
    release_row,
    table,
)

TARGETS = (
    "---\n"
    "wiki-stale-after-days: 365\n"
    "qa-separate-from-dev: false\n"
    "delivery-targets:\n"
    "  backend: {kind: deployment, target: production, environments: [staging]}\n"
    "  worker: {kind: deployment, target: production, environments: [staging]}\n"
    "---\n"
)

_SNAPSHOT: dict[str, object] = {}


def _cleanup_snapshot() -> None:
    folder = _SNAPSHOT.get("folder")
    if folder is not None:
        shutil.rmtree(str(folder), ignore_errors=True)


atexit.register(_cleanup_snapshot)


class ReleaseBoard(QaBoard):
    """A board with F-001 at `ready-for-release` (both apps passed through QA by the service) and the delivery targets declared."""

    def setUp(self) -> None:
        if not _SNAPSHOT:
            self.build_release_snapshot()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace"
        shutil.copytree(str(_SNAPSHOT["root"]), self.root)
        self.start_service(dict(_SNAPSHOT["tokens"]))  # type: ignore[arg-type]

    def build_release_snapshot(self) -> None:
        """Pass both apps through QA on a fresh board, then keep a copy of the closed workspace."""

        super().setUp()
        self.put(SETTINGS, TARGETS)
        page = self.qa_table([app_row("backend"), app_row("worker"), integration_row()])
        page = self.with_status("ready-for-release", "release", self.release_table([pending_row("backend"), pending_row("worker")], page))
        self.apply("qa-pass", [{"path": FEATURE, "content": page}], approver=self.quinn)
        self.assertEqual(("ready-for-release", "release"), self.status())
        tokens = dict(qa_support._SNAPSHOT["tokens"])  # type: ignore[arg-type]
        self.service.close()
        folder = tempfile.mkdtemp(prefix="prism-release-snapshot-")
        shutil.copytree(str(self.root), Path(folder) / "workspace")
        _SNAPSHOT.update({"folder": folder, "root": str(Path(folder) / "workspace"), "tokens": tokens})
        self.start_service(tokens)

    # -- building proposals ----------------------------------------------------------------------------------------------

    def released_page(self, rows: list[str], status: str = "released", owner: str = "none", content: str | None = None) -> str:
        """The feature page with its Release rows replaced by `rows` and the status set."""

        return self.with_status(status, owner, self.release_table(rows, content))

    def all_released(self, number: int = 1) -> tuple[str, str]:
        """The feature page and the record of a release of both apps."""

        feature = self.released_page([release_row("backend", number), release_row("worker", number)])
        record = record_page(number, [delivery("F-001", "backend"), delivery("F-001", "worker")])
        return feature, record

    def release_changes(self, number: int = 1, extra: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
        feature, record = self.all_released(number)
        return [{"path": FEATURE, "content": feature}, {"path": record_path(number), "content": record}, *(extra or [])]

    def release(self, number: int = 1, approver=None) -> dict:
        return self.apply("release-done", self.release_changes(number), approver=approver or self.owner)

    def records(self) -> list[str]:
        directory = self.root / RELEASES
        return sorted(path.name for path in directory.glob("REL-*.md")) if directory.is_dir() else []


class ReleaseTests(ReleaseBoard):
    """`ReleaseBoard` with the helpers the release test modules share."""

    def errors(self) -> set[str]:
        from prism_cli.wiki_lint import lint_wiki

        return {item.code for item in lint_wiki(self.root).diagnostics if item.severity == "error"}

    def record(self, number: int) -> tuple[dict, str]:
        from prism_cli.board_service import _parse_markdown

        return _parse_markdown(self.read(record_path(number)))

    def refusal(self, changes: list[dict[str, str]], approver=None, skill: str = "release-done") -> tuple[str, int]:
        error = self.refused(skill, changes, approver=approver or self.owner)
        return error.code, error.status

    def one_app(self, app: str, outcome: str = "released", number: int = 1, attempt: int = 1, **kwargs: str) -> tuple[str, str]:
        """The feature page and the record that settle `app` alone (the other app keeps its pending row)."""

        other = "worker" if app == "backend" else "backend"
        rows = {app: release_row(app, number, outcome=outcome, attempt=attempt, **kwargs), other: pending_row(other)}
        feature = self.released_page([rows["backend"], rows["worker"]], status="ready-for-release", owner="release")
        record = record_page(number, [delivery("F-001", app, outcome=outcome, attempt=attempt)])
        return feature, record

    def settle(self, feature: str, record: str, number: int = 1, approver=None) -> dict:
        return self.apply("release-done", [{"path": FEATURE, "content": feature}, {"path": record_path(number), "content": record}], approver=approver or self.owner)

    def refuse(self, feature: str, record: str, number: int = 1, approver=None) -> tuple[str, int]:
        return self.refusal([{"path": FEATURE, "content": feature}, {"path": record_path(number), "content": record}], approver)


FEATURE_TWO = "knowledge/wiki/features/F-002-second-export.md"
REQUIREMENT_TWO = "knowledge/wiki/app-requirements/F-002-backend.md"
TEXT_TWO = "A reviewer can export the second summary from the backend."


class ReleaseTwoFeatures(ReleaseTests):
    """`ReleaseTests` with a second feature, F-002, that shares the app `backend` with F-001 (it is `ready-for-release` on `build:backend#3`)."""

    ARTIFACT_TWO = "build:backend#3"

    def setUp(self) -> None:
        super().setUp()
        self.put(FEATURE_TWO, self.second_page("ready-for-release", "release", [pending_row("backend", artifact=self.ARTIFACT_TWO)]))
        self.put(REQUIREMENT_TWO, self.requirement("backend", "done").replace("F-001", "F-002"))
        board = self.read("knowledge/wiki/status-board.md").rstrip("\n")
        self.put("knowledge/wiki/status-board.md", f"{board}\n| F-002 | Second export | ready-for-release | release | not-needed | — | backend: ready-for-release | — |\n")
        index = self.read("knowledge/wiki/index.md")
        feature_line = "- [F-001 Document review](features/F-001-document-review.md): Review a document, summarize its key points, and record the review outcome.\n"
        requirement_line = "- [F-001 worker](app-requirements/F-001-worker.md): Requirements of F-001 for the worker app.\n"
        index = index.replace(feature_line, feature_line + "- [F-002 Second export](features/F-002-second-export.md): Export the second summary.\n")
        index = index.replace(requirement_line, requirement_line + "- [F-002 backend](app-requirements/F-002-backend.md): Requirements of F-002 for the backend app.\n")
        self.put("knowledge/wiki/index.md", index)

    def second_page(self, status: str, owner: str, release: list[str], artifact: str | None = None) -> str:
        """F-002 with its delivery and QA rows on `artifact` and the given Release rows."""

        from prism_cli.wiki_model import criterion_revision
        from tests.qa_support import delivery_row, qa_row

        artifact = artifact or self.ARTIFACT_TWO
        revision = criterion_revision("F-002", 1, ["backend"], False, "", TEXT_TWO)
        page = self.page(
            status,
            owner,
            ["backend"],
            [f"AC-1 [backend] {TEXT_TWO}"],
            delivery=[delivery_row("backend", artifact)],
            qa=[qa_row("backend", [f"AC-1@{revision}"], f"`{artifact}`")],
            release=release,
        )
        return page.replace("F-001", "F-002").replace("Document review", "Second export")

    def second_released(self, number: int, artifact: str | None = None, **kwargs: object) -> tuple[str, str]:
        """The page of F-002 with its backend released in record `number`, and that record."""

        artifact = artifact or self.ARTIFACT_TWO
        page = self.second_page("released", "none", [release_row("backend", number, version=artifact, **kwargs)], artifact)  # type: ignore[arg-type]
        record = record_page(number, [delivery("F-002", "backend", version=artifact)], features=["F-002"], title="Release of F-002", summary="F-002 is delivered to production.")
        return page, record
