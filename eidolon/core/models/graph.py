from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRef(BaseModel):
    source_type: str = Field(
        description="Authoritative source type (cloud_api, flow_logs, nmap, etc.)"
    )
    source_id: str = Field(description="Opaque source identifier (ARN, filename, record pointer)")
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    weight: float = Field(default=1.0, ge=0.0, description="Relative weighting for evidence fusion")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score 0-1")
    inferred: bool = Field(
        default=False,
        description="True when derived from inference rather than direct observation",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Source-specific metadata (ports, protocol, rule IDs)"
    )


class Node(BaseModel):
    """Base graph node with evidence tracking."""

    model_config = ConfigDict(populate_by_name=True)

    node_id: UUID = Field(default_factory=uuid4, alias="id")
    label: str = Field(description="Primary graph label, e.g. Asset or NetworkContainer")
    evidence: list[EvidenceRef] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_properties(self) -> dict[str, Any]:
        """Return serialisable properties for persistence layers."""
        props = self.model_dump(
            exclude={"evidence", "label"},
            by_alias=False,
            exclude_none=True,
        )
        props["node_id"] = str(self.node_id)
        props["created_at"] = self.created_at.isoformat()
        props["updated_at"] = self.updated_at.isoformat()
        return props


class Edge(BaseModel):
    """Typed edge with provenance and temporal bounds."""

    model_config = ConfigDict(populate_by_name=True)

    edge_id: UUID = Field(default_factory=uuid4, alias="id")
    type: str = Field(description="Relationship type such as MEMBER_OF or CAN_REACH")
    source: UUID = Field(description="Source node id")
    target: UUID = Field(description="Target node id")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    def to_properties(self) -> dict[str, Any]:
        props = self.model_dump(exclude={"evidence"}, exclude_none=True)
        props["edge_id"] = str(self.edge_id)
        props["source"] = str(self.source)
        props["target"] = str(self.target)
        props["first_seen"] = self.first_seen.isoformat()
        props["last_seen"] = self.last_seen.isoformat()
        return props


class GraphPath(BaseModel):
    """Path result used for queries and planning."""

    nodes: list[UUID]
    edges: list[str]
    cost: float | None = None
