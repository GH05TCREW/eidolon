from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from eidolon.api.dependencies import get_approval_store, require_roles
from eidolon.api.middleware.auth import IdentityContext
from eidolon.core.models.approval import ApprovalRecord
from eidolon.core.stores import ApprovalStore


class ApprovalRequest(BaseModel):
    action: str = Field(description="Action name requiring approval")
    ttl_seconds: int = Field(default=900, ge=60, le=86400)


class ApprovalResponse(BaseModel):
    token: str
    action: str
    expires_at: datetime


router = APIRouter(prefix="/approvals", tags=["approvals"])
_APPROVAL_STORE = Depends(get_approval_store)
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))


@router.post("/", response_model=ApprovalResponse)
def create_approval(
    request: ApprovalRequest,
    store: ApprovalStore = _APPROVAL_STORE,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
) -> ApprovalResponse:
    approval: ApprovalRecord = store.create(
        user_id=identity.user_id,
        action=request.action,
        ttl_seconds=request.ttl_seconds,
    )
    return ApprovalResponse(
        token=approval.token, action=approval.action, expires_at=approval.expires_at
    )
