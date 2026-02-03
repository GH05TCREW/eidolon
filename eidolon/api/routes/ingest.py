from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eidolon.api.dependencies import (
    get_audit_store,
    get_entity_resolver,
    get_graph_repository,
    require_roles,
)
from eidolon.api.middleware.auth import IdentityContext
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.event import AuditEvent, CollectorEvent
from eidolon.core.reasoning.entity import EntityResolver
from eidolon.core.stores import AuditStore
from eidolon.runtime.task_events import TaskEvent, task_event_bus
from eidolon.worker.ingest import IngestWorker


class IngestResponse(BaseModel):
    accepted: int


router = APIRouter(prefix="/ingest", tags=["ingest"])
_GRAPH_REPOSITORY = Depends(get_graph_repository)
_ENTITY_RESOLVER = Depends(get_entity_resolver)
_AUDIT_STORE = Depends(get_audit_store)
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))


@router.post("/events", response_model=IngestResponse)
def ingest_events(
    events: list[CollectorEvent],
    repository: GraphRepository = _GRAPH_REPOSITORY,
    resolver: EntityResolver = _ENTITY_RESOLVER,
    audit_store: AuditStore = _AUDIT_STORE,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
) -> IngestResponse:
    worker = IngestWorker(repository, resolver)
    worker.process(events)
    audit_store.add(
        AuditEvent(
            event_type="ingest",
            details={"accepted": len(events)},
            status="ok",
        )
    )
    task_event_bus.publish(
        TaskEvent(
            event_type="ingest",
            status="ok",
            payload={"accepted": len(events)},
        )
    )
    return IngestResponse(accepted=len(events))
