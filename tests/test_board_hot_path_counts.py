"""Operation-count guard for the slow board paths.

The board's hot paths (preview, query, graph build, apply and the idle change
scan) once cost seconds at a thousand features because they repeated the same
file reads, workspace walks and content hashes. Wall-clock assertions on that
are flaky, so this module counts the repeated work instead: how often each path
parses a wiki page, opens a file, fingerprints the workspace, validates the
graph inputs, lints the wiki and builds the graph. The counts are exact and
identical on every machine.

Each operation runs on a fresh workspace of 24 and of 48 features. The count at
both sizes must stay at or below ``slope * N + intercept`` and the growth from
24 to 48 features must stay at or below ``slope * 24``, which also catches a
path that turns quadratic. A regression shows up as a counted extra read. When a
change lowers a count, lower its ceiling in the same change.

``stat`` and ``realpath`` calls are not counted: they depend on how deep the
temporary folder sits.
"""

from __future__ import annotations

import builtins
import functools
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from prism_cli import wiki_graph, wiki_lint, wiki_model, wiki_transitions
from prism_cli.board_server import _LiveGraph, _SnapshotRefreshingService
from prism_cli.board_service import BoardService
from tests import real_temp  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]
SIZES = (24, 48)
READY_FEATURE = "F-001"
PREVIEW_ARGUMENTS = {"feature_id": READY_FEATURE, "action": "po-handoff", "inputs": {"semantic_review_acknowledged": True}}
METRICS = (
    "page_parses",
    "file_opens",
    "workspace_fingerprint",
    "validate_graph_inputs",
    "lint_wiki",
    "build_graph",
    "scandir",
)

# Ceilings per operation and metric as (slope, intercept): count(N) <= slope * N + intercept.
# They sit just above what the code does today. Lower them when a change removes work.
# The intercepts include the fixed pages and folders of every workspace: status-board.md, direction.md and
# roadmap.md, the topics, research, plans and technical-design folders and their format pages. No slope changed.
# A preview of a gated action (`po-handoff`) also returns the `review_revision` its human reads (CONTRACTS 1.3): the policy once more
# and one more read of each source file. That is a fixed cost, so it raises the `preview_transition` file_opens intercept and no slope.
CEILINGS: dict[str, dict[str, tuple[int, int]]] = {
    "preview_transition": {
        "page_parses": (1, 11),
        "file_opens": (1, 47),
        "workspace_fingerprint": (0, 0),
        "validate_graph_inputs": (0, 2),
        "lint_wiki": (0, 1),
        "build_graph": (0, 0),
        "scandir": (0, 100),
    },
    "query_blockers": {
        "page_parses": (1, 11),
        "file_opens": (3, 105),
        "workspace_fingerprint": (0, 2),
        "validate_graph_inputs": (0, 2),
        "lint_wiki": (0, 1),
        "build_graph": (0, 0),
        "scandir": (0, 118),
    },
    "build_graph": {
        "page_parses": (1, 11),
        "file_opens": (4, 172),
        "workspace_fingerprint": (0, 3),
        "validate_graph_inputs": (0, 0),
        "lint_wiki": (0, 1),
        "build_graph": (0, 1),
        "scandir": (0, 141),
    },
    # An unchanged workspace opens no file: the poller's stat gate trusts every old, unchanged file.
    "idle_scan": {
        "page_parses": (0, 0),
        "file_opens": (0, 2),
        "workspace_fingerprint": (0, 1),
        "validate_graph_inputs": (0, 1),
        "lint_wiki": (0, 0),
        "build_graph": (0, 0),
        "scandir": (0, 45),
    },
    # A fresh apply no longer evaluates the same files a second time in its roll-forward (the recovery revalidation).
    # It binds the operation's dependency set (the relevant-source snapshot of a reviewed recovery) before it validates, compares it
    # after, and compares it again before every write, so a dependency that appears while a write waits is a change. That is five
    # snapshots of a fixed cost each; no slope changed.
    "apply": {
        "page_parses": (1, 15),
        "file_opens": (4, 363),
        "workspace_fingerprint": (0, 4),
        "validate_graph_inputs": (0, 16),
        "lint_wiki": (0, 2),
        "build_graph": (0, 1),
        "scandir": (0, 563),
    },
}


def _load_workspace_builder() -> Callable[[Path, int], Any]:
    spec = importlib.util.spec_from_file_location("measure_board_scale", REPO_ROOT / "scripts" / "measure-board-scale.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_workspace


class _Counters:
    """Call counts that only grow while ``enabled`` is set."""

    def __init__(self) -> None:
        self.enabled = False
        self.calls: Counter[str] = Counter()

    def reset(self) -> None:
        self.calls.clear()


def _wrap_everywhere(stack: ExitStack, counters: _Counters, owner: Any, name: str, label: str) -> None:
    """Count calls to ``owner.name`` in every prism_cli module that imported it by name."""

    original = getattr(owner, name)

    @functools.wraps(original)
    def counted(*args: Any, **kwargs: Any) -> Any:
        if counters.enabled:
            counters.calls[label] += 1
        return original(*args, **kwargs)

    for module_name, module in list(sys.modules.items()):
        if module is None or not module_name.startswith("prism_cli"):
            continue
        if getattr(module, name, None) is original:
            stack.enter_context(patch.object(module, name, counted))


def _install_counters(stack: ExitStack, counters: _Counters) -> None:
    _wrap_everywhere(stack, counters, wiki_model, "parse_markdown_text", "page_parses")
    _wrap_everywhere(stack, counters, wiki_transitions, "workspace_fingerprint", "workspace_fingerprint")
    _wrap_everywhere(stack, counters, wiki_lint, "lint_wiki", "lint_wiki")
    _wrap_everywhere(stack, counters, wiki_graph, "build_graph", "build_graph")

    original_validate = BoardService.validate_graph_inputs

    @functools.wraps(original_validate)
    def counted_validate(self: BoardService) -> None:
        if counters.enabled:
            counters.calls["validate_graph_inputs"] += 1
        return original_validate(self)

    stack.enter_context(patch.object(BoardService, "validate_graph_inputs", counted_validate))

    original_open = io.open

    @functools.wraps(original_open)
    def counted_open(*args: Any, **kwargs: Any) -> Any:
        if counters.enabled:
            counters.calls["file_opens"] += 1
        return original_open(*args, **kwargs)

    stack.enter_context(patch.object(io, "open", counted_open))
    stack.enter_context(patch.object(builtins, "open", counted_open))

    original_scandir = os.scandir

    @functools.wraps(original_scandir)
    def counted_scandir(*args: Any, **kwargs: Any) -> Any:
        if counters.enabled:
            counters.calls["scandir"] += 1
        return original_scandir(*args, **kwargs)

    stack.enter_context(patch.object(os, "scandir", counted_scandir))


def _age_files(root: Path, seconds: int = 3600) -> None:
    """Make every workspace file look an hour old, so a stat-gated scan trusts it."""

    old = time.time() - seconds
    for current, directories, names in os.walk(root):
        directories[:] = [name for name in directories if name != ".prism"]
        for name in names:
            os.utime(Path(current) / name, (old, old))


class _Workspaces:
    """Pristine neutral workspaces with one human grant, copied fresh for every operation."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self._seeds: dict[int, tuple[Path, str]] = {}
        build_workspace = _load_workspace_builder()
        for size in SIZES:
            seed = base / f"seed-{size}"
            build_workspace(seed, size)
            with BoardService(seed) as service:
                token = service.create_participant(f"Counts {size}", "human", writable=True, roles="po")["token"]
            self._seeds[size] = (seed, token)

    def fresh(self, size: int) -> tuple[Path, BoardService, Any]:
        seed, token = self._seeds[size]
        destination = self.base / f"run-{uuid.uuid4().hex[:8]}"
        shutil.copytree(seed, destination)
        _age_files(destination)
        service = BoardService(destination).start()
        # `po-handoff` is gated: the human holds the `po` role and approves in a browser session.
        return destination, service, service.authenticate(token, via_session=True)


def _measure(counters: _Counters, run: Callable[[], Any]) -> dict[str, int]:
    counters.reset()
    counters.enabled = True
    try:
        run()
    finally:
        counters.enabled = False
    return {metric: counters.calls[metric] for metric in METRICS}


def collect_counts(workspaces: _Workspaces, counters: _Counters, size: int) -> dict[str, dict[str, int]]:
    """Run every hot path once on a fresh workspace of ``size`` features and count its work."""

    results: dict[str, dict[str, int]] = {}

    destination, service, actor = workspaces.fresh(size)
    try:
        results["preview_transition"] = _measure(counters, lambda: service.preview_transition(actor, **PREVIEW_ARGUMENTS))
    finally:
        service.close()

    destination, service, actor = workspaces.fresh(size)
    try:
        results["query_blockers"] = _measure(counters, lambda: service.query(actor, "blockers"))
    finally:
        service.close()

    destination, service, actor = workspaces.fresh(size)
    try:
        results["build_graph"] = _measure(counters, lambda: wiki_graph.build_graph(destination))
    finally:
        service.close()

    destination, service, actor = workspaces.fresh(size)
    try:
        graph = _LiveGraph(destination, service.validate_graph_inputs)
        results["idle_scan"] = _measure(counters, graph.refresh_now)
    finally:
        service.close()

    destination, service, actor = workspaces.fresh(size)
    try:
        graph = _LiveGraph(destination, service.validate_graph_inputs)
        api = _SnapshotRefreshingService(service, graph)
        preview = api.preview_transition(actor, **PREVIEW_ARGUMENTS)
        if preview["applicable"] is not True:
            raise AssertionError(f"The po-handoff preview for {READY_FEATURE} is not applicable: {preview['classification']}")
        review = api.get_preview(actor, preview["preview_id"])["approval"]["review_revision"]
        receipt: dict[str, Any] = {}

        def apply() -> None:
            receipt.update(api.apply(actor, preview["preview_id"], "count-" + uuid.uuid4().hex, review, True))

        results["apply"] = _measure(counters, apply)
        if receipt.get("state") != "applied":
            raise AssertionError(f"The counted apply did not apply: {receipt.get('state')}")
    finally:
        service.close()
    return results


class BoardHotPathCountTests(unittest.TestCase):
    counts: dict[int, dict[str, dict[str, int]]]

    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="prism-hot-path-")
        cls.addClassCleanup(temporary.cleanup)
        stack = ExitStack()
        cls.addClassCleanup(stack.close)
        counters = _Counters()
        _install_counters(stack, counters)
        workspaces = _Workspaces(Path(temporary.name))
        cls.counts = {size: collect_counts(workspaces, counters, size) for size in SIZES}

    def test_every_operation_has_a_ceiling_for_every_metric(self) -> None:
        for operation in self.counts[SIZES[0]]:
            self.assertEqual(set(METRICS), set(CEILINGS.get(operation, {})), operation)

    def test_counts_stay_within_the_ceilings(self) -> None:
        small, large = SIZES
        for operation, ceilings in CEILINGS.items():
            for metric, (slope, intercept) in ceilings.items():
                with self.subTest(operation=operation, metric=metric):
                    counted = {size: self.counts[size][operation][metric] for size in SIZES}
                    for size in SIZES:
                        self.assertLessEqual(
                            counted[size],
                            slope * size + intercept,
                            f"{operation} {metric} at N={size}: counted {counted[size]}, ceiling {slope}*N+{intercept}",
                        )
                    self.assertLessEqual(
                        counted[large] - counted[small],
                        slope * (large - small),
                        f"{operation} {metric} grew by {counted[large] - counted[small]} from N={small} to N={large}, ceiling {slope} per feature",
                    )


if __name__ == "__main__":
    unittest.main()
