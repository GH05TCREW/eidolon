from __future__ import annotations

from collections.abc import Iterable

from eidolon.config.settings import SandboxPermissions, get_settings
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.plan import PlanStep, ToolExecutionResult
from eidolon.runtime.sandbox import SandboxRuntime
from eidolon.runtime.tools.base import Tool
from eidolon.runtime.tools.browser import BrowserTool
from eidolon.runtime.tools.file_edit import FileEditTool
from eidolon.runtime.tools.finish import FinishTool
from eidolon.runtime.tools.graph_query import GraphQueryTool
from eidolon.runtime.tools.terminal import TerminalTool
from eidolon.runtime.tools.thinking import ThinkingTool
from eidolon.runtime.tools.todo import TodoTool

DEFAULT_ACTION_TOOL: dict[str, str] = {
    "run_command": "terminal",
    "open_url": "browser",
    "edit_file": "file_edit",
    "graph_query": "graph_query",
}


class ExecutionEngine:
    """Execute plan steps using the registered tool runtime."""

    def __init__(
        self,
        repository: GraphRepository,
        runtime_settings: SandboxPermissions | None = None,
        extra_tools: Iterable[Tool] | None = None,
    ) -> None:
        settings = runtime_settings or get_settings().sandbox
        self.runtime = SandboxRuntime(settings=settings)
        self.runtime.register_tool(TerminalTool())
        self.runtime.register_tool(BrowserTool())
        self.runtime.register_tool(FileEditTool())
        self.runtime.register_tool(ThinkingTool())
        self.runtime.register_tool(TodoTool())
        self.runtime.register_tool(FinishTool())
        self.runtime.register_tool(GraphQueryTool(repository))
        for tool in extra_tools or []:
            self.runtime.register_tool(tool)

    def _resolve_tool(self, step: PlanStep) -> str | None:
        if step.tool_hint:
            return step.tool_hint
        return DEFAULT_ACTION_TOOL.get(step.action_type)

    def execute_step(self, step: PlanStep, dry_run: bool = True) -> ToolExecutionResult:
        tool = self._resolve_tool(step)
        if not tool:
            return ToolExecutionResult(
                step_id=step.step_id,
                tool=None,
                status="skipped",
                error="no tool mapped for action_type",
            )

        if dry_run:
            return ToolExecutionResult(step_id=step.step_id, tool=tool, status="dry_run")

        payload = step.parameters or {}
        output = self.runtime.execute(tool, payload)
        status = "ok"
        error = None
        if isinstance(output, dict):
            if output.get("error"):
                status = "error"
                error = str(output.get("error"))
            elif output.get("returncode") not in (None, 0):
                status = "error"
                error = output.get("stderr") or "command failed"

        return ToolExecutionResult(
            step_id=step.step_id,
            tool=tool,
            status=status,
            output=output if isinstance(output, dict) else {"result": output},
            error=error,
        )
