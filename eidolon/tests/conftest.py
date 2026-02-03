from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from uuid import UUID

import pytest

from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.asset import Asset, Identity, NetworkContainer, Policy
from eidolon.core.models.graph import Edge, EvidenceRef, GraphPath, Node


class InMemoryGraphRepository(GraphRepository):
    def __init__(self) -> None:
        self.nodes: dict[UUID, Node] = {}
        self.edges: list[Edge] = []
        self.adjacency: dict[UUID, list[Edge]] = defaultdict(list)

    def upsert_node(self, node: Node) -> None:
        self.nodes[node.node_id] = node

    def upsert_edge(self, edge: Edge) -> None:
        self.edges.append(edge)
        self.adjacency[edge.source].append(edge)

    def find_paths(self, source: UUID, target: UUID, max_depth: int = 4) -> list[GraphPath]:
        queue: deque[tuple[UUID, list[UUID], list[str]]] = deque()
        queue.append((source, [source], []))
        paths: list[GraphPath] = []
        while queue:
            node_id, path, rels = queue.popleft()
            if node_id == target:
                paths.append(GraphPath(nodes=path, edges=rels, cost=float(len(rels))))
                continue
            if len(path) > max_depth:
                continue
            for edge in self.adjacency.get(node_id, []):
                if edge.target not in path:
                    queue.append((edge.target, [*path, edge.target], [*rels, edge.type]))
        return paths

    def get_neighbors(
        self, node_id: UUID, relationship_types: Sequence[str] | None = None
    ) -> list[UUID]:
        neighbors = []
        for edge in self.adjacency.get(node_id, []):
            if relationship_types and edge.type not in relationship_types:
                continue
            neighbors.append(edge.target)
        return neighbors

    def upsert_asset(self, asset: Asset) -> None:
        self.upsert_node(asset)

    def upsert_network(self, network: NetworkContainer) -> None:
        self.upsert_node(network)

    def upsert_identity(self, identity: Identity) -> None:
        self.upsert_node(identity)

    def upsert_policy(self, policy: Policy) -> None:
        self.upsert_node(policy)

    def get_node(self, node_id: UUID) -> Node | None:
        return self.nodes.get(node_id)

    def list_nodes(self, label: str | None = None, limit: int = 100) -> list[Node]:
        nodes = list(self.nodes.values())
        if label:
            nodes = [n for n in nodes if n.label == label]
        return nodes[:limit]

    def run_cypher(self, cypher: str, parameters: dict | None = None) -> Iterable[dict]:
        return []

    def find_asset_by_identifier(self, identifier: str) -> Asset | None:
        for node in self.nodes.values():
            if isinstance(node, Asset) and identifier in node.identifiers:
                return node
            if (
                node.label == "Asset"
                and getattr(node, "identifiers", None)
                and identifier in node.identifiers
            ):
                return node  # type: ignore[return-value]
        return None

    def find_network_by_cidr_or_name(self, cidr_or_name: str) -> NetworkContainer | None:
        for node in self.nodes.values():
            if isinstance(node, NetworkContainer) and (
                node.cidr == cidr_or_name or node.name == cidr_or_name
            ):
                return node
        return None

    def find_identity_by_name(self, name: str) -> Identity | None:
        for node in self.nodes.values():
            if isinstance(node, Identity) and node.name == name:
                return node
        return None

    def get_edge_evidence(self, edge_id: UUID) -> list[EvidenceRef]:
        for edge in self.edges:
            if edge.edge_id == edge_id:
                return list(edge.evidence)
        return []

    def clear(self) -> int:
        count = len(self.nodes)
        self.nodes.clear()
        self.edges.clear()
        self.adjacency.clear()
        return count


@pytest.fixture
def in_memory_repo() -> InMemoryGraphRepository:
    return InMemoryGraphRepository()


@pytest.fixture
def viewer_headers() -> dict:
    return {"x-roles": "viewer"}


@pytest.fixture
def planner_headers() -> dict:
    return {"x-roles": "planner"}


@pytest.fixture
def executor_headers() -> dict:
    return {"x-roles": "executor"}
