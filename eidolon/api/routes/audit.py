from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from eidolon.api.dependencies import get_audit_store, require_roles
from eidolon.api.middleware.auth import IdentityContext
from eidolon.core.models.event import AuditEvent
from eidolon.core.stores import AuditStore

router = APIRouter(prefix="/audit", tags=["audit"])
_AUDIT_STORE = Depends(get_audit_store)
_VIEWER_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))
_PAGE_QUERY = Query(1, ge=1, description="Page number (1-indexed)")
_PAGE_SIZE_QUERY = Query(50, ge=1, le=500, description="Events per page")
_EVENT_TYPE_QUERY = Query(None, description="Filter by event type")
_START_DATE_QUERY = Query(None, description="Filter events after this date")
_END_DATE_QUERY = Query(None, description="Filter events before this date")


class AuditListResponse(BaseModel):
    events: list[AuditEvent]
    total: int
    page: int
    page_size: int
    has_more: bool


class AuditClearResponse(BaseModel):
    status: str
    deleted: int


@router.get("/", response_model=AuditListResponse)
def list_events(
    page: int = _PAGE_QUERY,
    page_size: int = _PAGE_SIZE_QUERY,
    event_type: str | None = _EVENT_TYPE_QUERY,
    start_date: datetime | None = _START_DATE_QUERY,
    end_date: datetime | None = _END_DATE_QUERY,
    store: AuditStore = _AUDIT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> AuditListResponse:
    events = store.list_filtered(
        page=page,
        page_size=page_size,
        event_type=event_type,
        start_date=start_date,
        end_date=end_date,
    )
    total = store.count_filtered(
        event_type=event_type,
        start_date=start_date,
        end_date=end_date,
    )
    has_more = (page * page_size) < total

    return AuditListResponse(
        events=events,
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )


@router.get("/{audit_id}", response_model=AuditEvent)
def get_event(
    audit_id: UUID,
    store: AuditStore = _AUDIT_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> AuditEvent:
    event = store.get(audit_id)
    if not event:
        raise HTTPException(status_code=404, detail="audit event not found")
    return event


@router.delete("/", response_model=AuditClearResponse)
def clear_events(
    store: AuditStore = _AUDIT_STORE,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
) -> AuditClearResponse:
    deleted = store.delete_older_than(datetime.max)
    return AuditClearResponse(status="cleared", deleted=deleted)
