from __future__ import annotations

from typing import Any

from eidolon.runtime.tools.base import Tool


class FinishTool(Tool):
    name = "finish"
    description = "Signal task completion and return final payload."
    sandbox_execution = False

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief completion summary",
                },
                "details": {
                    "type": "object",
                    "description": "Optional structured completion payload",
                },
            },
            "required": [],
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"result": payload}
