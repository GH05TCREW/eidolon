from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from eidolon.api.dependencies import (
    get_approval_store,
    get_audit_store,
    get_graph_repository,
    get_llm_client,
    require_roles,
)
from eidolon.api.middleware.auth import IdentityContext
from eidolon.config.settings import get_settings
from eidolon.core.graph.algorithms import blast_radius
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.event import AuditEvent
from eidolon.core.models.plan import (
    BlastRadius,
    EntityRef,
    ExecutionRequest,
    ExecutionResponse,
    PlanStep,
    ToolExecutionResult,
)
from eidolon.core.reasoning.llm import LiteLLMClient
from eidolon.core.reasoning.planner import Planner
from eidolon.core.stores import ApprovalStore, AuditStore
from eidolon.runtime.executor import ExecutionEngine
from eidolon.runtime.task_events import TaskEvent, task_event_bus


class PlanRequest(BaseModel):
    intent: str = Field(description="Intent to satisfy (natural language)")
    target: EntityRef = Field(description="Primary target entity for the plan")


class PlanResponse(BaseModel):
    steps: list[PlanStep]
    blast_radius: BlastRadius | None = None


router = APIRouter(prefix="/plan", tags=["plan"])
_APPROVAL_STORE = Depends(get_approval_store)
_AUDIT_STORE = Depends(get_audit_store)
_GRAPH_REPOSITORY = Depends(get_graph_repository)
_LLM_CLIENT = Depends(get_llm_client)
_PLANNER_EXECUTOR_IDENTITY = Depends(require_roles("planner", "executor"))
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))


@router.post("/", response_model=PlanResponse)
def plan_endpoint(
    request: PlanRequest,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    audit_store: AuditStore = _AUDIT_STORE,
    llm_client: LiteLLMClient = _LLM_CLIENT,
    identity: IdentityContext = _PLANNER_EXECUTOR_IDENTITY,
) -> PlanResponse:
    planner = Planner(llm_client=llm_client)
    steps = planner.generate_plan(intent=request.intent, target=request.target)
    radius = None
    if request.target.entity_id:
        radius = blast_radius(repository, [request.target.entity_id], depth=2)
    audit_store.add(
        AuditEvent(
            event_type="plan",
            details={
                "intent": request.intent,
                "target": request.target.model_dump(mode="json"),
                "steps": len(steps),
            },
            status="ok",
        )
    )
    return PlanResponse(steps=steps, blast_radius=radius)


@router.post("/execute", response_model=ExecutionResponse)
def execute_endpoint(
    request: ExecutionRequest,
    approval_store: ApprovalStore = _APPROVAL_STORE,
    audit_store: AuditStore = _AUDIT_STORE,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
) -> ExecutionResponse:
    needs_approval = request.requires_approval or any(
        step.requires_approval for step in request.steps
    )
    if not request.dry_run and needs_approval:
        if not request.approval_token:
            raise HTTPException(status_code=403, detail="approval token required for execution")
        approval = approval_store.get_by_token(request.approval_token)
        if not approval or approval.action != "execute":
            raise HTTPException(status_code=403, detail="invalid approval token")

    settings = get_settings()
    engine = ExecutionEngine(repository, runtime_settings=settings.sandbox)
    task_event_bus.publish(
        TaskEvent(
            event_type="execute",
            status="started",
            payload={
                "dry_run": request.dry_run,
                "steps": len(request.steps),
            },
        )
    )
    results: list[ToolExecutionResult] = []
    for step in request.steps:
        task_event_bus.publish(
            TaskEvent(
                event_type="execute.step",
                status="started",
                payload={"step_id": step.step_id, "action_type": step.action_type},
            )
        )
        result = engine.execute_step(step, dry_run=request.dry_run)
        results.append(result)
        task_event_bus.publish(
            TaskEvent(
                event_type="execute.step",
                status=result.status,
                payload={
                    "step_id": step.step_id,
                    "action_type": step.action_type,
                    "tool": result.tool,
                    "error": result.error,
                },
            )
        )
    status = "ok" if all(result.status != "error" for result in results) else "partial_failure"
    task_event_bus.publish(
        TaskEvent(
            event_type="execute",
            status=status,
            payload={
                "dry_run": request.dry_run,
                "steps": len(request.steps),
                "status": status,
            },
        )
    )
    audit_event = AuditEvent(
        event_type="execute",
        details={
            "dry_run": request.dry_run,
            "steps": len(request.steps),
            "status": status,
            "results": [result.model_dump() for result in results],
        },
        status=status,
    )
    audit_store.add(audit_event)
    return ExecutionResponse(
        request=request,
        results=results,
        status=status,
        audit_id=audit_event.audit_id,
    )
