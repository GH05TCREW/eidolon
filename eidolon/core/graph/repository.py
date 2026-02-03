from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from uuid import UUID

from eidolon.core.models.asset import Asset, Identity, NetworkContainer, Policy
from eidolon.core.models.graph import Edge, EvidenceRef, GraphPath, Node


class GraphRepository(ABC):
    """Abstract repository interface for Eidolon's evidence-backed graph."""

    @abstractmethod
    def upsert_node(self, node: Node) -> None:
        """Create or update a node with evidence."""

    @abstractmethod
    def upsert_edge(self, edge: Edge) -> None:
        """Create or update a relationship with evidence."""

    @abstractmethod
    def find_paths(self, source: UUID, target: UUID, max_depth: int = 4) -> list[GraphPath]:
        """Return paths between two nodes."""

    @abstractmethod
    def get_neighbors(
        self, node_id: UUID, relationship_types: Sequence[str] | None = None
    ) -> list[UUID]:
        """Return neighbor node IDs for the given node."""

    @abstractmethod
    def get_node(self, node_id: UUID) -> Node | None:
        """Return a node by id if present."""

    @abstractmethod
    def list_nodes(self, label: str | None = None, limit: int = 100) -> list[Node]:
        """List nodes, optionally filtered by label."""

    @abstractmethod
    def upsert_asset(self, asset: Asset) -> None:
        """Helper to persist assets with standard label."""

    @abstractmethod
    def upsert_network(self, network: NetworkContainer) -> None:
        """Helper to persist network containers."""

    @abstractmethod
    def upsert_identity(self, identity: Identity) -> None:
        """Helper to persist identities."""

    @abstractmethod
    def upsert_policy(self, policy: Policy) -> None:
        """Helper to persist policies."""

    @abstractmethod
    def run_cypher(self, cypher: str, parameters: dict | None = None) -> Iterable[dict]:
        """Execute arbitrary Cypher for advanced queries (used sparingly)."""

    @abstractmethod
    def find_asset_by_identifier(self, identifier: str) -> Asset | None:
        """Return an Asset node that matches the identifier (IP, hostname, MAC)."""

    @abstractmethod
    def find_network_by_cidr_or_name(self, cidr_or_name: str) -> NetworkContainer | None:
        """Return a NetworkContainer node by CIDR or name."""

    @abstractmethod
    def find_identity_by_name(self, name: str) -> Identity | None:
        """Return an Identity node by canonical name."""

    @abstractmethod
    def get_edge_evidence(self, edge_id: UUID) -> list[EvidenceRef]:
        """Return evidence references attached to the edge."""

    @abstractmethod
    def clear(self) -> int:
        """Delete all nodes and edges from the graph and return count of removed nodes."""
