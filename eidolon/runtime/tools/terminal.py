from __future__ import annotations

import subprocess
from typing import Any

from eidolon.runtime.tools.base import Tool


class TerminalTool(Tool):
    name = "terminal"
    description = "Execute shell commands in a sandboxed environment."
    sandbox_execution = True

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory for the command (optional)",
                },
            },
            "required": ["command"],
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = payload.get("command")
        workdir = payload.get("workdir")
        if not command:
            return {"error": "command is required"}
        result = subprocess.run(  # noqa: S602
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=workdir,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
