from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from eidolon.api.dependencies import (
    get_approval_store,
    get_graph_repository,
    get_llm_client,
)
from eidolon.api.middleware.auth import extract_bearer_token, resolve_identity
from eidolon.config.settings import get_settings
from eidolon.core.graph.algorithms import blast_radius
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


class AgentPlanRequest(BaseModel):
    intent: str
    target: EntityRef


class AgentRunRequest(BaseModel):
    intent: str
    target: EntityRef | None = None
    dry_run: bool = True
    approval_token: str | None = None


router = APIRouter(prefix="/agents", tags=["agents"])


@router.websocket("/ws")
async def agent_ws(websocket: WebSocket) -> None:
    settings = get_settings()
    token = extract_bearer_token(websocket.headers)
    token = (
        token or websocket.query_params.get("token") or websocket.query_params.get("access_token")
    )
    identity, error = resolve_identity(websocket.headers, settings.auth, token=token)
    if error or not identity:
        await websocket.close(code=4401)
        return
    if not identity.has_role("executor"):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    approval_store: ApprovalStore = get_approval_store()
    repository = get_graph_repository()
    llm_client: LiteLLMClient = get_llm_client()
    planner = Planner(llm_client=llm_client)

    def _execute_request(request: ExecutionRequest) -> ExecutionResponse:
        needs_approval = request.requires_approval or any(
            step.requires_approval for step in request.steps
        )
        if not request.dry_run and needs_approval:
            if not request.approval_token:
                raise RuntimeError("approval token required for execution")
            approval = approval_store.get_by_token(request.approval_token)
            if not approval or approval.action != "execute":
                raise RuntimeError("invalid approval token")

        engine = ExecutionEngine(repository, runtime_settings=settings.sandbox)
        results: list[ToolExecutionResult] = []
        for step in request.steps:
            results.append(engine.execute_step(step, dry_run=request.dry_run))
        status = "ok" if all(result.status != "error" for result in results) else "partial_failure"
        return ExecutionResponse(request=request, results=results, status=status)

    try:
        await websocket.send_json({"type": "connected", "status": "ok"})
        async for message in websocket.iter_text():
            request_id = None
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "status": "error", "error": "invalid json"}
                )
                continue
            if isinstance(payload, dict):
                request_id = payload.get("request_id") or payload.get("id")
            message_type = payload.get("type") if isinstance(payload, dict) else None
            message_type = message_type or (
                payload.get("action") if isinstance(payload, dict) else None
            )
            data = payload.get("payload") if isinstance(payload, dict) else None
            data = data or (payload.get("request") if isinstance(payload, dict) else payload)
            response: dict[str, object]
            try:
                if message_type == "plan":
                    request = AgentPlanRequest.model_validate(data)
                    steps = planner.generate_plan(intent=request.intent, target=request.target)
                    radius = (
                        blast_radius(repository, [request.target.entity_id], depth=2)
                        if request.target.entity_id
                        else None
                    )
                    response = {
                        "type": "plan",
                        "status": "ok",
                        "data": {
                            "steps": [step.model_dump() for step in steps],
                            "blast_radius": radius.model_dump() if radius else None,
                        },
                    }
                elif message_type == "execute":
                    request = ExecutionRequest.model_validate(data)
                    exec_response = _execute_request(request)
                    response = {
                        "type": "execute",
                        "status": "ok",
                        "data": exec_response.model_dump(),
                    }
                elif message_type == "run":
                    request = AgentRunRequest.model_validate(data)
                    steps = planner.generate_plan(
                        intent=request.intent,
                        target=request.target
                        or EntityRef(entity_type="Asset", display_name="unknown"),
                    )
                    exec_request = ExecutionRequest(
                        dry_run=request.dry_run,
                        steps=steps,
                        approval_token=request.approval_token,
                        requires_approval=any(step.requires_approval for step in steps),
                    )
                    if exec_request.dry_run:
                        response = {
                            "type": "run",
                            "status": "ok",
                            "data": {"steps": [step.model_dump() for step in steps]},
                        }
                    else:
                        exec_response = _execute_request(exec_request)
                        response = {
                            "type": "run",
                            "status": "ok",
                            "data": exec_response.model_dump(),
                        }
                elif message_type == "ping":
                    response = {"type": "pong", "status": "ok"}
                else:
                    response = {
                        "type": "error",
                        "status": "error",
                        "error": "unsupported message type",
                    }
            except (RuntimeError, ValidationError) as exc:
                response = {"type": "error", "status": "error", "error": str(exc)}

            if request_id is not None:
                response["request_id"] = request_id
            await websocket.send_json(response)
    except WebSocketDisconnect:
        return
