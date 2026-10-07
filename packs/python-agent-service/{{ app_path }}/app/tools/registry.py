"""The tools the model may call. The registry is the allow-list: a name that is not here is never run."""

from __future__ import annotations

from collections.abc import Sequence

from app.providers.base import ToolSpec
from app.tools.base import Tool


class ToolRegistry:
    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.mutates:
                raise ValueError(
                    f"Tool {tool.name!r} changes data. A tool here only reads; to propose a change, return a preview "
                    "that the user confirms in the application."
                )
            if tool.name in self._tools:
                raise ValueError(f"Two tools are named {tool.name!r}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(name=tool.name, description=tool.description, input_schema=tool.Arguments.model_json_schema())
            for tool in self._tools.values()
        ]
