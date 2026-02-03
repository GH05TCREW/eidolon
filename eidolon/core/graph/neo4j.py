from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from contextlib import suppress
from datetime import datetime
from uuid import UUID

from neo4j import GraphDatabase, Session
from pydantic import ValidationError

from eidolon.config.settings import get_settings
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.asset import (
    ActionType,
    Asset,
    Capability,
    EvidenceSource,
    Identity,
    NetworkContainer,
    Policy,
    Tool,
)
from eidolon.core.models.graph import Edge, EvidenceRef, GraphPath, Node


class Neo4jGraphRepository(GraphRepository):
    """Neo4j implementation of the GraphRepository using Cypher queries."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        settings = get_settings()
        self._uri = uri or settings.neo4j.uri
        self._user = user or settings.neo4j.user
        self._password = password or settings.neo4j.password
        self._database = database or settings.neo4j.database
        self._driver = GraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
            notifications_disabled_categories=["UNRECOGNIZED"],
        )

    def close(self) -> None:
        self._driver.close()

    def _session(self) -> Session:
        return self._driver.session(database=self._database)

    def _build_node(self, label: str, props: dict, evidence: list[EvidenceRef]) -> Node:
        from neo4j.time import DateTime as Neo4jDateTime

        payload = dict(props or {})
        payload["label"] = label
        payload["evidence"] = evidence

        # Convert Neo4j DateTime objects to Python datetime
        for key in ("created_at", "updated_at"):
            if key in payload and isinstance(payload[key], Neo4jDateTime):
                payload[key] = payload[key].to_native()

        # Deserialize known JSON fields
        payload = self._deserialize_from_neo4j(payload)

        model_map = {
            "Asset": Asset,
            "NetworkContainer": NetworkContainer,
            "Identity": Identity,
            "Policy": Policy,
            "Tool": Tool,
            "Capability": Capability,
            "ActionType": ActionType,
            "EvidenceSource": EvidenceSource,
        }
        model = model_map.get(label, Node)
        try:
            return model.model_validate(payload)
        except ValidationError:
            return Node.model_validate(payload)

    @staticmethod
    def _parse_evidence(raw: list[dict]) -> list[EvidenceRef]:
        from neo4j.time import DateTime as Neo4jDateTime

        evidence: list[EvidenceRef] = []
        for item in raw or []:
            if not item or not item.get("source_type"):
                continue
            # Convert Neo4j DateTime to Python datetime
            if "collected_at" in item and isinstance(item["collected_at"], Neo4jDateTime):
                item["collected_at"] = item["collected_at"].to_native()
            # Deserialize metadata field only
            if "metadata" in item and isinstance(item["metadata"], str):
                try:
                    item["metadata"] = json.loads(item["metadata"])
                except (json.JSONDecodeError, TypeError, ValueError):
                    item["metadata"] = {}
            evidence.append(EvidenceRef.model_validate(item))
        return evidence

    @staticmethod
    def _serialize_for_neo4j(data: dict) -> dict:
        """Recursively serialize nested dicts to JSON strings for Neo4j."""
        result = {}
        for key, value in data.items():
            if isinstance(value, dict) or (
                isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
            ):
                result[key] = json.dumps(value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _deserialize_from_neo4j(data: dict, json_fields: set[str] | None = None) -> dict:
        """Deserialize JSON strings back to dicts for known JSON fields."""
        if json_fields is None:
            json_fields = {"metadata", "rules", "privileges", "groups"}

        result = dict(data)
        for key, value in result.items():
            if key in json_fields and isinstance(value, str):
                with suppress(json.JSONDecodeError, TypeError, ValueError):
                    result[key] = json.loads(value)
        return result

    def upsert_node(self, node: Node) -> None:
        props = self._serialize_for_neo4j(node.to_properties())

        evidence = []
        for ev in node.evidence:
            evidence.append(self._serialize_for_neo4j(ev.model_dump()))

        cypher = f"""
        MERGE (n:{node.label} {{node_id: $node_id}})
        ON CREATE SET n.created_at = datetime()
        SET n += $props, n.updated_at = datetime()
        WITH n
        UNWIND $evidence AS ev
          MERGE (e:Evidence {{source_type: ev.source_type, source_id: ev.source_id}})
          SET e.collected_at = datetime(ev.collected_at),
              e.metadata = ev.metadata,
              e.weight = ev.weight,
              e.confidence = ev.confidence,
              e.inferred = ev.inferred
          MERGE (n)-[r:HAS_EVIDENCE]->(e)
          SET r.weight = ev.weight, r.confidence = ev.confidence
        """
        with self._session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    cypher,
                    node_id=str(node.node_id),
                    props=props,
                    evidence=evidence,
                )
            )

    def upsert_edge(self, edge: Edge) -> None:
        evidence = []
        for ev in edge.evidence:
            evidence.append(self._serialize_for_neo4j(ev.model_dump()))

        cypher = f"""
        MATCH (source {{node_id: $source_id}})
        MATCH (target {{node_id: $target_id}})
        MERGE (source)-[r:{edge.type}]->(target)
        SET r.edge_id = $edge_id,
            r.confidence = $confidence,
            r.first_seen = coalesce(r.first_seen, datetime($first_seen)),
            r.last_seen = datetime($last_seen)
        WITH r
        UNWIND $evidence AS ev
          MERGE (e:Evidence {{source_type: ev.source_type, source_id: ev.source_id}})
          SET e.collected_at = datetime(ev.collected_at),
              e.metadata = ev.metadata,
              e.weight = ev.weight,
              e.confidence = ev.confidence,
              e.inferred = ev.inferred
          MERGE (:EdgeEvidence {{edge_id: $edge_id}})-[re:RECORDED_BY]->(e)
          SET re.weight = ev.weight, re.confidence = ev.confidence
        """
        with self._session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    cypher,
                    source_id=str(edge.source),
                    target_id=str(edge.target),
                    edge_id=str(edge.edge_id),
                    confidence=edge.confidence,
                    first_seen=edge.first_seen.isoformat(),
                    last_seen=edge.last_seen.isoformat(),
                    evidence=evidence,
                )
            )

    def find_paths(self, source: UUID, target: UUID, max_depth: int = 4) -> list[GraphPath]:
        cypher = """
        MATCH (source {node_id: $source_id}), (target {node_id: $target_id})
        MATCH p = (source)-[*1..5]->(target)
        WHERE length(p) <= $max_depth
        WITH p,
             reduce(
               cost = 0.0,
               rel in relationships(p) | cost + coalesce(rel.confidence, 1.0)
             ) AS path_cost
        ORDER BY length(p), path_cost
        LIMIT 10
        RETURN [n IN nodes(p) | n.node_id] AS node_ids,
               [r IN relationships(p) | type(r)] AS rels,
               path_cost
        """
        with self._session() as session:
            result = session.execute_read(
                lambda tx: tx.run(
                    cypher, source_id=str(source), target_id=str(target), max_depth=max_depth
                ).data()
            )
        paths: list[GraphPath] = []
        for record in result:
            paths.append(
                GraphPath(
                    nodes=[UUID(node_id) for node_id in record["node_ids"]],
                    edges=record["rels"],
                    cost=record["path_cost"],
                )
            )
        return paths

    def get_neighbors(
        self, node_id: UUID, relationship_types: Sequence[str] | None = None
    ) -> list[UUID]:
        rel_filter = ""
        params: dict = {"node_id": str(node_id)}
        if relationship_types:
            rel_filter = "WHERE type(r) IN $rel_types"
            params["rel_types"] = list(relationship_types)
        cypher = f"""
        MATCH (n {{node_id: $node_id}})-[r]->(neighbor)
        {rel_filter}
        RETURN DISTINCT neighbor.node_id AS node_id
        """
        with self._session() as session:
            result = session.execute_read(lambda tx: tx.run(cypher, **params).data())
        return [UUID(record["node_id"]) for record in result]

    def upsert_asset(self, asset: Asset) -> None:
        self.upsert_node(asset)

    def upsert_network(self, network: NetworkContainer) -> None:
        self.upsert_node(network)

    def upsert_identity(self, identity: Identity) -> None:
        self.upsert_node(identity)

    def upsert_policy(self, policy: Policy) -> None:
        self.upsert_node(policy)

    def run_cypher(self, cypher: str, parameters: dict | None = None) -> Iterable[dict]:
        with self._session() as session:
            result = session.execute_read(lambda tx: tx.run(cypher, parameters or {}).data())
        return result

    def find_asset_by_identifier(self, identifier: str) -> Asset | None:
        cypher = """
        MATCH (n:Asset)
        WHERE $identifier IN n.identifiers OR n.node_id = $identifier
        OPTIONAL MATCH (n)-[:HAS_EVIDENCE]->(e:Evidence)
        RETURN properties(n) AS props,
               head(labels(n)) AS label,
               collect({
                 source_type: e.source_type,
                 source_id: e.source_id,
                 collected_at: e.collected_at,
                 weight: e.weight,
                 confidence: e.confidence,
                 inferred: e.inferred,
                 metadata: e.metadata
               }) AS evidence
        LIMIT 1
        """
        with self._session() as session:
            record = session.execute_read(lambda tx: tx.run(cypher, identifier=identifier).single())
        if not record:
            return None
        props = record["props"] or {}
        evidence = self._parse_evidence(record.get("evidence", []))
        node = self._build_node("Asset", props, evidence)
        return node if isinstance(node, Asset) else None

    def find_network_by_cidr_or_name(self, cidr_or_name: str) -> NetworkContainer | None:
        cypher = """
        MATCH (n:NetworkContainer)
        WHERE n.cidr = $value OR n.name = $value
        OPTIONAL MATCH (n)-[:HAS_EVIDENCE]->(e:Evidence)
        RETURN properties(n) AS props,
               head(labels(n)) AS label,
               collect({
                 source_type: e.source_type,
                 source_id: e.source_id,
                 collected_at: e.collected_at,
                 weight: e.weight,
                 confidence: e.confidence,
                 inferred: e.inferred,
                 metadata: e.metadata
               }) AS evidence
        LIMIT 1
        """
        with self._session() as session:
            record = session.execute_read(lambda tx: tx.run(cypher, value=cidr_or_name).single())
        if not record:
            return None
        props = record["props"] or {}
        evidence = self._parse_evidence(record.get("evidence", []))
        node = self._build_node("NetworkContainer", props, evidence)
        return node if isinstance(node, NetworkContainer) else None

    def find_identity_by_name(self, name: str) -> Identity | None:
        cypher = """
        MATCH (n:Identity)
        WHERE n.name = $name
        OPTIONAL MATCH (n)-[:HAS_EVIDENCE]->(e:Evidence)
        RETURN properties(n) AS props,
               head(labels(n)) AS label,
               collect({
                 source_type: e.source_type,
                 source_id: e.source_id,
                 collected_at: e.collected_at,
                 weight: e.weight,
                 confidence: e.confidence,
                 inferred: e.inferred,
                 metadata: e.metadata
               }) AS evidence
        LIMIT 1
        """
        with self._session() as session:
            record = session.execute_read(lambda tx: tx.run(cypher, name=name).single())
        if not record:
            return None
        props = record["props"] or {}
        evidence = self._parse_evidence(record.get("evidence", []))
        node = self._build_node("Identity", props, evidence)
        return node if isinstance(node, Identity) else None

    def get_edge_evidence(self, edge_id: UUID) -> list[EvidenceRef]:
        cypher = """
        MATCH (:EdgeEvidence {edge_id: $edge_id})-[:RECORDED_BY]->(e:Evidence)
        RETURN collect({
          source_type: e.source_type,
          source_id: e.source_id,
          collected_at: e.collected_at,
          weight: e.weight,
          confidence: e.confidence,
          inferred: e.inferred,
          metadata: e.metadata
        }) AS evidence
        """
        with self._session() as session:
            record = session.execute_read(lambda tx: tx.run(cypher, edge_id=str(edge_id)).single())
        return self._parse_evidence(record["evidence"]) if record else []

    def clear(self) -> int:
        cypher = """
        MATCH (n)
        WITH count(n) AS node_count
        MATCH (n)
        DETACH DELETE n
        RETURN node_count
        """
        with self._session() as session:
            record = session.execute_write(lambda tx: tx.run(cypher).single())
        if not record:
            return 0
        return int(record.get("node_count") or 0)

    def get_node(self, node_id: UUID) -> Node | None:
        cypher = """
        MATCH (n {node_id: $node_id})
        OPTIONAL MATCH (n)-[:HAS_EVIDENCE]->(e:Evidence)
        RETURN properties(n) AS props,
               head(labels(n)) AS label,
               collect({
                 source_type: e.source_type,
                 source_id: e.source_id,
                 collected_at: e.collected_at,
                 weight: e.weight,
                 confidence: e.confidence,
                 inferred: e.inferred,
                 metadata: e.metadata
               }) AS evidence
        """
        with self._session() as session:
            record = session.execute_read(lambda tx: tx.run(cypher, node_id=str(node_id)).single())
        if not record:
            return None
        props = record["props"] or {}
        label = record["label"] or "Node"
        evidence = self._parse_evidence(record.get("evidence", []))
        return self._build_node(label, props, evidence)

    def list_nodes(self, label: str | None = None, limit: int = 100) -> list[Node]:
        where = ""
        params: dict = {"limit": limit}
        if label:
            where = f"WHERE n:{label}"
        cypher = f"""
        MATCH (n)
        {where}
        OPTIONAL MATCH (n)-[:HAS_EVIDENCE]->(e:Evidence)
        WITH n, collect({{
          source_type: e.source_type,
          source_id: e.source_id,
          collected_at: e.collected_at,
          weight: e.weight,
          confidence: e.confidence,
          inferred: e.inferred,
          metadata: e.metadata
        }}) AS evidence
        RETURN properties(n) AS props, head(labels(n)) AS label, evidence
        LIMIT $limit
        """
        with self._session() as session:
            records = session.execute_read(lambda tx: tx.run(cypher, **params).data())
        nodes: list[Node] = []
        for record in records:
            props = record["props"] or {}
            lbl = record["label"] or "Node"
            evidence = self._parse_evidence(record.get("evidence", []))
            nodes.append(self._build_node(lbl, props, evidence))
        return nodes

    @staticmethod
    def _coerce_datetime(value: object | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
