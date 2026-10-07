"""The audit log of tool calls: one JSON line per call, with the user and the request IDs.

A line names the tool and the argument names (cut short, because a model chooses them), the outcome and the
duration. It never carries a token, an argument value or a tool result, which are the user's data.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from typing import Any

AUDIT_LOGGER = "agent.audit"

Sink = Callable[[dict[str, Any]], None]


def log_sink(record: dict[str, Any]) -> None:
    logging.getLogger(AUDIT_LOGGER).info(json.dumps(record, sort_keys=True))


def configure_audit_logging() -> None:
    """Send audit lines to stderr, once, whatever the host application configured for the root logger."""

    logger = logging.getLogger(AUDIT_LOGGER)
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class AuditLog:
    def __init__(self, sink: Sink = log_sink) -> None:
        self._sink = sink

    def tool_call(
        self,
        *,
        user_id: str,
        request_id: str,
        tool: str,
        argument_names: list[str],
        outcome: str,
        duration_ms: int,
    ) -> None:
        """`outcome` is `ok`, `error`, `unknown_tool` or `invalid_arguments`."""

        self._sink(
            {
                "event": "tool_call",
                "user_id": user_id,
                "request_id": request_id,
                "tool": tool[:64],
                "argument_names": sorted(name[:64] for name in argument_names[:20]),
                "outcome": outcome,
                "duration_ms": duration_ms,
            }
        )

    def budget_refused(self, *, user_id: str, request_id: str, reason: str) -> None:
        self._sink({"event": "budget_refused", "user_id": user_id, "request_id": request_id, "reason": reason})
