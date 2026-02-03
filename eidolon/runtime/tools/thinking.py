from __future__ import annotations

from typing import Any

from eidolon.runtime.tools.base import Tool


class ThinkingTool(Tool):
    name = "thinking"
    description = "Structured reasoning scratchpad."
    sandbox_execution = False

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thoughts": {
                    "type": "string",
                    "description": "Reasoning or plan notes",
                }
            },
            "required": ["thoughts"],
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        thoughts = payload.get("thoughts", "")
        return {"thoughts": thoughts, "status": "captured"}
