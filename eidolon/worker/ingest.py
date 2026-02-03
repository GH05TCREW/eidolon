from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.asset import Asset, Identity, NetworkContainer
from eidolon.core.models.event import CollectorEvent
from eidolon.core.models.graph import Edge, EvidenceRef
from eidolon.core.reasoning.entity import EntityResolver


class IngestWorker:
    """Ingest normalized collector events into the graph repository."""

    def __init__(self, repository: GraphRepository, resolver: EntityResolver) -> None:
        self.repository = repository
        self.resolver = resolver

    @staticmethod
    def _merge_evidence(
        existing: list[EvidenceRef], incoming: list[EvidenceRef]
    ) -> list[EvidenceRef]:
        merged: dict[tuple[str, str], EvidenceRef] = {
            (ev.source_type, ev.source_id): ev for ev in existing
        }
        for ev in incoming:
            merged[(ev.source_type, ev.source_id)] = ev
        return list(merged.values())

    @staticmethod
    def _merge_asset(existing: Asset, incoming: Asset) -> Asset:
        identifiers = sorted(set(existing.identifiers) | set(incoming.identifiers))
        metadata = {**existing.metadata, **incoming.metadata}
        kind = existing.kind
        if incoming.kind and incoming.kind != existing.kind and existing.kind == "host":
            kind = incoming.kind
        merged = existing.model_copy(
            update={
                "kind": kind,
                "env": existing.env or incoming.env,
                "criticality": existing.criticality or incoming.criticality,
                "owner_team": existing.owner_team or incoming.owner_team,
                "lifecycle_state": existing.lifecycle_state or incoming.lifecycle_state,
                "identifiers": identifiers,
                "metadata": metadata,
                "evidence": IngestWorker._merge_evidence(existing.evidence, incoming.evidence),
            }
        )
        return merged

    @staticmethod
    def _merge_network(existing: NetworkContainer, incoming: NetworkContainer) -> NetworkContainer:
        metadata = {**existing.metadata, **incoming.metadata}
        return existing.model_copy(
            update={
                "name": existing.name or incoming.name,
                "network_type": existing.network_type or incoming.network_type,
                "metadata": metadata,
                "evidence": IngestWorker._merge_evidence(existing.evidence, incoming.evidence),
            }
        )

    @staticmethod
    def _merge_identity(existing: Identity, incoming: Identity) -> Identity:
        groups = sorted(set(existing.groups) | set(incoming.groups))
        privileges = sorted(set(existing.privileges) | set(incoming.privileges))
        metadata = {**existing.metadata, **incoming.metadata}
        return existing.model_copy(
            update={
                "identity_type": existing.identity_type or incoming.identity_type,
                "groups": groups,
                "privileges": privileges,
                "metadata": metadata,
                "evidence": IngestWorker._merge_evidence(existing.evidence, incoming.evidence),
            }
        )

    @staticmethod
    def _deterministic_edge_id(edge_type: str, source: UUID, target: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, f"{edge_type}:{source}:{target}")

    def _resolve_node_ref(self, ref: Any, evidence: EvidenceRef) -> UUID | None:
        if ref is None:
            return None
        if isinstance(ref, UUID):
            return ref if self.repository.get_node(ref) else None
        if isinstance(ref, str):
            try:
                node_id = UUID(ref)
                return node_id if self.repository.get_node(node_id) else None
            except ValueError:
                pass
            asset = self.repository.find_asset_by_identifier(ref)
            if asset:
                return asset.node_id
            network = self.repository.find_network_by_cidr_or_name(ref)
            if network:
                return network.node_id
            identity = self.repository.find_identity_by_name(ref)
            if identity:
                return identity.node_id
            asset = self.resolver.resolve_asset(
                payload={"ip": ref},
                source_type=evidence.source_type,
                source_id=evidence.source_id,
                confidence=evidence.confidence,
            )
            self.repository.upsert_asset(asset)
            return asset.node_id
        if isinstance(ref, dict):
            entity_type = ref.get("entity_type") or ref.get("type") or "Asset"
            payload = ref.get("payload") or ref
            if entity_type == "NetworkContainer":
                network = self.resolver.resolve_network(
                    payload=payload,
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    confidence=evidence.confidence,
                )
                existing = self._find_existing_network(network)
                if existing:
                    network = self._merge_network(existing, network)
                self.repository.upsert_network(network)
                return network.node_id
            if entity_type == "Identity":
                identity = self.resolver.resolve_identity(
                    payload=payload,
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    confidence=evidence.confidence,
                )
                existing = self._find_existing_identity(identity)
                if existing:
                    identity = self._merge_identity(existing, identity)
                self.repository.upsert_identity(identity)
                return identity.node_id
            asset = self.resolver.resolve_asset(
                payload=payload,
                source_type=evidence.source_type,
                source_id=evidence.source_id,
                confidence=evidence.confidence,
            )
            existing = self._find_existing_asset(asset)
            if existing:
                asset = self._merge_asset(existing, asset)
            self.repository.upsert_asset(asset)
            return asset.node_id
        return None

    def _find_existing_asset(self, asset: Asset) -> Asset | None:
        for identifier in asset.identifiers:
            match = self.repository.find_asset_by_identifier(identifier)
            if match:
                return match
        return None

    def _find_existing_network(self, network: NetworkContainer) -> NetworkContainer | None:
        return self.repository.find_network_by_cidr_or_name(network.cidr)

    def _find_existing_identity(self, identity: Identity) -> Identity | None:
        return self.repository.find_identity_by_name(identity.name)

    def _maybe_link_network(self, asset: Asset, payload: dict, evidence: EvidenceRef) -> None:
        cidr = payload.get("cidr") or payload.get("network_cidr")
        if not cidr:
            return
        network_payload = {
            "cidr": cidr,
            "name": payload.get("network_name") or payload.get("network"),
            "network_type": payload.get("network_type"),
            "metadata": payload.get("network_metadata", {}),
        }
        network = self.resolver.resolve_network(
            payload=network_payload,
            source_type=evidence.source_type,
            source_id=evidence.source_id,
            confidence=evidence.confidence,
        )
        existing_network = self._find_existing_network(network)
        if existing_network:
            network = self._merge_network(existing_network, network)
        self.repository.upsert_network(network)

        edge = Edge(
            edge_id=self._deterministic_edge_id("MEMBER_OF", asset.node_id, network.node_id),
            type="MEMBER_OF",
            source=asset.node_id,
            target=network.node_id,
            evidence=[evidence],
        )
        self.repository.upsert_edge(edge)

    def process_event(self, event: CollectorEvent) -> None:
        if event.entity_type == "Asset":
            asset = self.resolver.resolve_asset(
                payload=event.payload,
                source_type=event.source_type,
                source_id=event.source_id or str(event.event_id),
                confidence=event.confidence,
            )
            event_evidence = asset.evidence[-1] if asset.evidence else None
            existing = self._find_existing_asset(asset)
            if existing:
                asset = self._merge_asset(existing, asset)
            self.repository.upsert_asset(asset)
            if event_evidence:
                self._maybe_link_network(asset, event.payload, event_evidence)
        elif event.entity_type == "NetworkContainer":
            network = self.resolver.resolve_network(
                payload=event.payload,
                source_type=event.source_type,
                source_id=event.source_id or str(event.event_id),
                confidence=event.confidence,
            )
            existing = self._find_existing_network(network)
            if existing:
                network = self._merge_network(existing, network)
            self.repository.upsert_network(network)
        elif event.entity_type == "Identity":
            identity = self.resolver.resolve_identity(
                payload=event.payload,
                source_type=event.source_type,
                source_id=event.source_id or str(event.event_id),
                confidence=event.confidence,
            )
            existing = self._find_existing_identity(identity)
            if existing:
                identity = self._merge_identity(existing, identity)
            self.repository.upsert_identity(identity)
        elif event.entity_type == "Edge":
            payload = event.payload or {}
            edge_type = (
                payload.get("edge_type") or payload.get("type") or payload.get("relationship")
            )
            if not edge_type:
                return
            evidence = self.resolver.build_evidence(
                source_type=event.source_type,
                source_id=event.source_id or str(event.event_id),
                confidence=event.confidence,
                metadata={"payload": payload},
            )
            source_ref = (
                payload.get("source")
                or payload.get("source_id")
                or payload.get("source_identifier")
            )
            target_ref = (
                payload.get("target")
                or payload.get("target_id")
                or payload.get("target_identifier")
            )
            source_id = self._resolve_node_ref(source_ref, evidence)
            target_id = self._resolve_node_ref(target_ref, evidence)
            if not source_id or not target_id:
                return
            edge = Edge(
                edge_id=self._deterministic_edge_id(edge_type, source_id, target_id),
                type=edge_type,
                source=source_id,
                target=target_id,
                confidence=float(payload.get("confidence", event.confidence)),
                evidence=[evidence],
            )
            self.repository.upsert_edge(edge)

    def process(self, events: Iterable[CollectorEvent]) -> None:
        for event in events:
            self.process_event(event)
