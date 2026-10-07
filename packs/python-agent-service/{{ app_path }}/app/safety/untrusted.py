"""Untrusted content is data, never instructions.

The user's question and every tool result reach the model inside an `<untrusted-data>` envelope: the content is
JSON-encoded, and `<`, `>` and `&` are written as `\\u003c`, `\\u003e` and `\\u0026`, so the content can never contain
the closing tag. The system prompt (`app/agent/prompts.py`) tells the model that the content of an envelope is
information to answer from and is never to be obeyed. This module is the only place that builds an envelope.
"""

from __future__ import annotations

import json
import re
from typing import Any

_KIND = re.compile(r"[a-z][a-z_]*")
_ENVELOPE = re.compile(r'<untrusted-data kind="([a-z][a-z_]*)">(.*)</untrusted-data>', re.DOTALL)
_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", " ": "\\u2028", " ": "\\u2029"}


def as_data(kind: str, value: Any) -> str:
    """The envelope for a JSON-serializable value. `kind` names what it is, such as `user_question`."""

    if not _KIND.fullmatch(kind):
        raise ValueError("kind must be lowercase words joined by underscores")
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for character, escape in _ESCAPES.items():
        payload = payload.replace(character, escape)
    return f'<untrusted-data kind="{kind}">{payload}</untrusted-data>'


def unwrap(envelope: str) -> tuple[str, Any]:
    """The kind and the decoded value of an envelope. Tests and the fake provider read data back this way."""

    match = _ENVELOPE.fullmatch(envelope)
    if match is None:
        raise ValueError("Not an untrusted-data envelope")
    return match.group(1), json.loads(match.group(2))
