"""Participant tokens: kept in memory, redacted from saved text, scanned for in saved files.

Tokens never reach a file, a log, a prompt or a transcript. The registry holds
them for the process lifetime; ``redact`` removes them from any text before it
is saved, and ``scan_tree`` is the last line of defence before the run ends.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

REDACTION = "<REDACTED-TOKEN>"
# A shorter value would match unrelated text, so it is not treated as a token.
MIN_TOKEN_LENGTH = 16


class TokenRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def add(self, label: str, token: str) -> None:
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"The token for {label} is too short to track safely.")
        self._tokens[label] = token

    def get(self, label: str) -> str:
        return self._tokens[label]

    def labels(self) -> list[str]:
        return sorted(self._tokens)

    def redact(self, text: str) -> str:
        for token in sorted(self._tokens.values(), key=len, reverse=True):
            text = text.replace(token, REDACTION)
        return text

    def labels_in(self, data: bytes) -> list[str]:
        """Labels of the tokens that appear in ``data`` (UTF-8 bytes)."""

        return [label for label, token in sorted(self._tokens.items()) if token.encode("utf-8") in data]

    def scan_tree(self, root: Path, *, skip: Iterable[Path] = ()) -> list[tuple[str, list[str]]]:
        """Every file under ``root`` that holds a token, as ``(relative path, labels)``.

        ``skip`` lists folders that are not scanned (the installed virtual environment).
        """

        skipped = [path.resolve() for path in skip]
        hits: list[tuple[str, list[str]]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if any(parent == skipped_path for skipped_path in skipped for parent in (resolved, *resolved.parents)):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            labels = self.labels_in(data)
            if labels:
                hits.append((path.relative_to(root).as_posix(), labels))
        return hits

    def scrub_file(self, path: Path) -> None:
        """Replace every token in a text file in place. Used only after a scan found one."""

        data = path.read_bytes()
        for token in sorted(self._tokens.values(), key=len, reverse=True):
            data = data.replace(token.encode("utf-8"), REDACTION.encode("utf-8"))
        path.write_bytes(data)
