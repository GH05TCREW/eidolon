from __future__ import annotations

from enum import Enum

from eidolon.config.settings import SandboxPermissions
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.plan import (
    EntityRef,
    ExecutionRequest,
    ExecutionResponse,
    ToolExecutionResult,
)
from eidolon.core.reasoning.llm import LiteLLMClient
from eidolon.core.reasoning.planner import Planner
from eidolon.core.stores import ApprovalStore
from eidolon.runtime.executor import ExecutionEngine
from eidolon.runtime.tools.base import Tool


class AgentState(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    STOPPED = "stopped"


class Agent:
    """Single-agent runtime that plans and optionally executes with policy/approval checks."""

    def __init__(
        self,
        tools: dict[str, Tool] | None,
        llm_client: LiteLLMClient,
        max_iterations: int = 8,
        *,
        repository: GraphRepository | None = None,
        approval_store: ApprovalStore | None = None,
        runtime_settings: SandboxPermissions | None = None,
    ) -> None:
        self.tools = tools or {}
        self.llm_client = llm_client
        self.repository = repository
        self.approval_store = approval_store
        self.runtime_settings = runtime_settings
        self.max_iterations = max_iterations
        self.state = AgentState.WAITING
        self.trace: list[dict] = []

    def _execute(
        self,
        request: ExecutionRequest,
    ) -> tuple[list[ToolExecutionResult], str]:
        if not self.repository:
            raise RuntimeError("repository required for execution")
        engine = ExecutionEngine(
            self.repository,
            runtime_settings=self.runtime_settings,
            extra_tools=self.tools.values(),
        )
        results: list[ToolExecutionResult] = []
        for step in request.steps:
            result = engine.execute_step(step, dry_run=request.dry_run)
            results.append(result)
        status = "ok" if all(result.status != "error" for result in results) else "partial_failure"
        self.trace.append(
            {
                "event": "execute",
                "dry_run": request.dry_run,
                "status": status,
            }
        )
        return results, status

    def run_intent(
        self,
        intent: str,
        target: EntityRef | None = None,
        *,
        dry_run: bool = True,
        approval_token: str | None = None,
    ) -> dict:
        self.state = AgentState.RUNNING
        self.trace = []
        resolved_target = target or EntityRef(entity_type="Asset", display_name="unknown")
        planner = Planner(llm_client=self.llm_client)
        steps = planner.generate_plan(intent=intent, target=resolved_target)
        if len(steps) > self.max_iterations:
            steps = steps[: self.max_iterations]
            self.trace.append({"event": "plan.truncated", "limit": self.max_iterations})
        self.trace.append({"event": "plan", "steps": len(steps)})

        if dry_run:
            self.state = AgentState.STOPPED
            return {
                "intent": intent,
                "status": "planned",
                "steps": [step.model_dump() for step in steps],
                "trace": self.trace,
            }

        # Execute the plan
        request = ExecutionRequest(
            dry_run=False,
            steps=steps,
            requires_approval=any(step.requires_approval for step in steps),
            approval_token=approval_token,
        )

        if request.requires_approval:
            if not approval_token:
                self.state = AgentState.STOPPED
                raise RuntimeError("approval token required for execution")
            if not self.approval_store:
                self.state = AgentState.STOPPED
                raise RuntimeError("approval store unavailable")
            approval = self.approval_store.get_by_token(approval_token)
            if not approval or approval.action != "execute":
                self.state = AgentState.STOPPED
                raise RuntimeError("invalid approval token")

        results, status = self._execute(request)
        self.state = AgentState.STOPPED
        response = ExecutionResponse(request=request, results=results, status=status)
        return {
            "intent": intent,
            "status": status,
            "steps": [step.model_dump() for step in steps],
            "execution": response.model_dump(),
            "trace": self.trace,
        }
