from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CollectorEvent(BaseModel):
    """Normalized collector event before graph ingestion."""

    event_id: UUID = Field(default_factory=uuid4)
    source_type: str = Field(description="Collector type (network, cloud, identity, traffic)")
    source_id: str | None = Field(default=None, description="Opaque identifier from the collector")
    entity_type: str = Field(
        description="Target entity type: Asset, NetworkContainer, Identity, etc."
    )
    payload: dict[str, Any] = Field(default_factory=dict, description="Normalized event payload")
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AuditEvent(BaseModel):
    """Audit event stored in Postgres for traceability."""

    audit_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(description="prompt, tool_call, execution, approval")
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="pending")
