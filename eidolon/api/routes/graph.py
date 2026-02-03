from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j.exceptions import Neo4jError
from pydantic import BaseModel, Field

from eidolon.api.dependencies import get_graph_repository, require_roles
from eidolon.api.middleware.auth import IdentityContext
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.asset import Asset, NetworkContainer
from eidolon.core.models.graph import GraphPath, Node

router = APIRouter(prefix="/graph", tags=["graph"])
_GRAPH_REPOSITORY = Depends(get_graph_repository)
_VIEWER_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))
_LIMIT_QUERY = Query(100, ge=1, le=500)
_MAX_DEPTH_QUERY = Query(4, ge=1, le=8)
_NODE_LIMIT_QUERY = Query(200, ge=1, le=1000)
_EDGE_LIMIT_QUERY = Query(400, ge=1, le=2000)


class GraphClearResponse(BaseModel):
    status: str
    nodes_deleted: int


class GraphOverviewNode(BaseModel):
    node_id: UUID
    label: str
    name: str | None = None
    kind: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphOverviewEdge(BaseModel):
    source: UUID
    target: UUID
    type: str
    confidence: float | None = None


class GraphOverviewResponse(BaseModel):
    nodes: list[GraphOverviewNode]
    edges: list[GraphOverviewEdge]


class GraphQueryRequest(BaseModel):
    cypher: str
    parameters: dict[str, Any] | None = None


class GraphQueryResponse(BaseModel):
    records: list[dict[str, Any]]


def _coerce_metadata(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _parse_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


@router.get("/assets", response_model=list[Asset])
def list_assets(
    limit: int = _LIMIT_QUERY,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> list[Node]:
    return repository.list_nodes(label="Asset", limit=limit)


@router.get("/networks", response_model=list[NetworkContainer])
def list_networks(
    limit: int = _LIMIT_QUERY,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> list[Node]:
    return repository.list_nodes(label="NetworkContainer", limit=limit)


@router.get("/assets/{asset_id}", response_model=Asset)
def get_asset(
    asset_id: UUID,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> Node:
    node = repository.get_node(asset_id)
    if not node or node.label != "Asset":
        raise HTTPException(status_code=404, detail="asset not found")
    return node


@router.get("/paths", response_model=list[GraphPath])
def get_paths(
    source_id: UUID,
    target_id: UUID,
    max_depth: int = _MAX_DEPTH_QUERY,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> list[GraphPath]:
    return repository.find_paths(source_id, target_id, max_depth)


@router.delete("/", response_model=GraphClearResponse)
def clear_graph(
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
) -> GraphClearResponse:
    deleted = repository.clear()
    return GraphClearResponse(status="cleared", nodes_deleted=deleted)


@router.get("/overview", response_model=GraphOverviewResponse)
def graph_overview(
    node_limit: int = _NODE_LIMIT_QUERY,
    edge_limit: int = _EDGE_LIMIT_QUERY,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> GraphOverviewResponse:
    nodes_result = list(
        repository.run_cypher(
            """
            MATCH (n)
            RETURN n.node_id AS node_id,
                   head(labels(n)) AS label,
                   n.cidr AS cidr,
                   n.name AS name,
                   n.kind AS kind,
                   n.metadata AS metadata
            LIMIT $limit
            """,
            {"limit": node_limit},
        )
    )

    nodes: list[GraphOverviewNode] = []
    node_ids: list[str] = []
    for record in nodes_result:
        node_id = _parse_uuid(record.get("node_id"))
        if not node_id:
            continue
        metadata = _coerce_metadata(record.get("metadata"))

        # Build display name priority: IP -> CIDR -> hostname -> name -> UUID.
        display_name = None
        if metadata:
            display_name = metadata.get("ip") or metadata.get("hostname")
        if not display_name:
            display_name = record.get("cidr") or record.get("name") or str(node_id)

        node = GraphOverviewNode(
            node_id=node_id,
            label=str(record.get("label") or "Node"),
            name=display_name,
            kind=record.get("kind"),
            metadata=metadata,
        )
        nodes.append(node)
        node_ids.append(str(node_id))

    if not node_ids:
        return GraphOverviewResponse(nodes=[], edges=[])

    edges_result = list(
        repository.run_cypher(
            """
            MATCH (a)-[r]->(b)
            WHERE a.node_id IN $node_ids AND b.node_id IN $node_ids
            RETURN a.node_id AS source,
                   b.node_id AS target,
                   type(r) AS type,
                   r.confidence AS confidence
            LIMIT $limit
            """,
            {"node_ids": node_ids, "limit": edge_limit},
        )
    )

    edges: list[GraphOverviewEdge] = []
    for record in edges_result:
        source = _parse_uuid(record.get("source"))
        target = _parse_uuid(record.get("target"))
        if not source or not target:
            continue
        edges.append(
            GraphOverviewEdge(
                source=source,
                target=target,
                type=str(record.get("type") or "RELATED"),
                confidence=record.get("confidence"),
            )
        )

    return GraphOverviewResponse(nodes=nodes, edges=edges)


@router.post("/query", response_model=GraphQueryResponse)
def execute_cypher_query(
    request: GraphQueryRequest,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> GraphQueryResponse:
    """
    Execute a raw Cypher query against the graph database.

    This endpoint allows direct Cypher queries for advanced use cases.
    Results are returned as a list of records (dictionaries).
    """
    try:
        results = repository.run_cypher(request.cypher, request.parameters or {})
        records = [dict(record) for record in results]
        return GraphQueryResponse(records=records)
    except (Neo4jError, TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Query execution failed: {exc!s}",
        ) from exc
