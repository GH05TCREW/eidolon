from __future__ import annotations

from pydantic import BaseModel, Field

from eidolon.core.models.plan import EntityRef, PlanStep
from eidolon.core.reasoning.llm import LiteLLMClient
from eidolon.core.reasoning.prompts import PLAN_PROMPT_TEMPLATE


class LLMPlanStep(BaseModel):
    action_type: str
    tool_hint: str | None = None
    rationale: str = ""
    rollback: str | None = None
    risk: str | None = None
    requires_approval: bool = False
    parameters: dict = Field(default_factory=dict)


class LLMPlanDraft(BaseModel):
    steps: list[LLMPlanStep] = Field(default_factory=list)


class Planner:
    """Intent -> Plan generator that defers heavy lifting to LLMs in later phases."""

    def __init__(self, llm_client: LiteLLMClient | None = None) -> None:
        self.llm_client = llm_client

    def generate_plan(self, intent: str, target: EntityRef) -> list[PlanStep]:
        fallback = [
            PlanStep(
                action_type="analyze",
                target=target,
                rationale=intent,
                rollback="No-op rollback for analysis step.",
                risk="low",
                requires_approval=False,
            )
        ]

        if not self.llm_client or not self.llm_client.is_available():
            return fallback

        prompt = PLAN_PROMPT_TEMPLATE.format(intent=intent, target=target.model_dump())
        try:
            draft = self.llm_client.generate_structured(prompt, LLMPlanDraft)
        except Exception:  # noqa: BLE001
            return fallback

        if not draft.steps:
            return fallback

        steps: list[PlanStep] = []
        for draft_step in draft.steps:
            steps.append(
                PlanStep(
                    action_type=draft_step.action_type,
                    target=target,
                    tool_hint=draft_step.tool_hint,
                    rationale=draft_step.rationale,
                    rollback=draft_step.rollback,
                    risk=draft_step.risk,
                    requires_approval=draft_step.requires_approval,
                    parameters=draft_step.parameters,
                )
            )
        return steps
