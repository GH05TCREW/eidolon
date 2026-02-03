from __future__ import annotations

from pathlib import Path
from typing import Any

from eidolon.runtime.tools.base import Tool


class FileEditTool(Tool):
    name = "file_edit"
    description = "Read or write files with explicit intents."
    sandbox_execution = True

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "write"],
                    "description": "Action to perform on the file",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (for write action)",
                },
            },
            "required": ["action", "path"],
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "read")).lower()
        path = payload.get("path")
        if not path:
            return {"error": "path is required"}
        target = Path(path)
        if action == "read":
            if not target.exists():
                return {"error": f"{path} not found"}
            return {"path": path, "content": target.read_text(encoding="utf-8")}
        if action == "write":
            content = payload.get("content", "")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return {"path": path, "status": "written"}
        return {"error": f"unsupported action {action}"}
