from __future__ import annotations

from typing import Any

from eidolon.config.settings import SandboxPermissions, get_settings
from eidolon.runtime.tools.base import Tool


class SandboxRuntime:
    """Sandbox runtime that enforces capability gates before dispatching tools."""

    def __init__(self, settings: SandboxPermissions | None = None) -> None:
        self.settings = settings or get_settings().sandbox
        self.active_tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self.active_tools[tool.name] = tool

    def _is_tool_allowed(self, tool: Tool, payload: dict[str, Any]) -> tuple[bool, str | None]:
        settings = self.settings
        name = tool.name
        if settings.allowed_tools is not None and name not in settings.allowed_tools:
            return False, f"tool {name} is not in allowlist"
        if name in settings.blocked_tools:
            return False, f"tool {name} is blocked"
        if not tool.sandbox_execution and not settings.allow_unsafe_tools:
            return False, f"tool {name} is not permitted in the sandbox"
        if name == "terminal" and not settings.allow_shell:
            return False, "terminal tool is disabled"
        if name == "browser" and not settings.allow_network:
            return False, "browser tool is disabled"
        if name == "file_edit":
            action = str(payload.get("action", "read")).lower()
            if action == "write" and not settings.allow_file_write:
                return False, "file write operations are disabled"
        return True, None

    def execute(self, tool_name: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        tool = self.active_tools.get(tool_name)
        if not tool:
            return {"error": f"tool {tool_name} not registered"}
        safe_payload = payload or {}
        allowed, reason = self._is_tool_allowed(tool, safe_payload)
        if not allowed:
            return {"error": reason or "tool execution not permitted"}
        return tool.run(safe_payload)
