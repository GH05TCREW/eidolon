from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from eidolon.core.models.graph import GraphPath


class EntityRef(BaseModel):
    """Resolved entity reference used throughout planning and execution."""

    entity_id: UUID | None = Field(default=None, alias="id")
    entity_type: str = Field(description="Node label such as Asset, NetworkContainer, Identity")
    display_name: str | None = Field(default=None)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GraphQuery(BaseModel):
    """Representation of a graph query to keep LLM outputs typed."""

    cypher: str
    parameters: dict = Field(default_factory=dict)


class PlanStep(BaseModel):
    """Single step in a generated plan."""

    step_id: str = Field(default_factory=lambda: str(uuid4()))
    action_type: str = Field(
        description="Action type identifier (run_command, change_firewall_rule, etc.)"
    )
    target: EntityRef = Field(description="Primary entity or resource targeted by the step")
    tool_hint: str | None = Field(default=None, description="Preferred tool for execution")
    rationale: str = Field(default="", description="Why this step exists")
    rollback: str | None = Field(default=None, description="Rollback guidance or command")
    risk: str | None = Field(default=None, description="Risk or blast radius summary")
    requires_approval: bool = Field(default=True)
    parameters: dict = Field(
        default_factory=dict,
        description="Execution payload or tool parameters for this step",
    )


class BlastRadius(BaseModel):
    """Output of blast radius estimation."""

    affected_nodes: list[UUID] = Field(default_factory=list)
    paths: list[GraphPath] = Field(default_factory=list)
    score: float = Field(default=0.0, ge=0.0, description="Higher is riskier")


class ExecutionRequest(BaseModel):
    """Request to execute a plan in a gated runtime."""

    dry_run: bool = Field(default=True)
    steps: list[PlanStep] = Field(default_factory=list)
    requires_approval: bool = Field(default=True)
    approval_reason: str | None = Field(default=None)
    approval_token: str | None = Field(
        default=None, description="Token proving approval for execution"
    )


class PlanDraft(BaseModel):
    """LLM-friendly wrapper for plan steps."""

    steps: list[PlanStep] = Field(default_factory=list)


class ToolExecutionResult(BaseModel):
    """Result of executing a single plan step."""

    step_id: str
    tool: str | None = None
    status: str = Field(description="ok, skipped, dry_run, error")
    output: dict = Field(default_factory=dict)
    error: str | None = None


class ExecutionResponse(BaseModel):
    """Response for execution requests, including per-step results."""

    request: ExecutionRequest
    results: list[ToolExecutionResult] = Field(default_factory=list)
    status: str = Field(default="ok")
    audit_id: UUID | None = None
