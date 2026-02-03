from __future__ import annotations

from collections.abc import Iterable
from difflib import SequenceMatcher

from eidolon.core.models.asset import Asset, Identity, NetworkContainer
from eidolon.core.models.graph import EvidenceRef


class EntityResolver:
    """Entity resolution with lightweight fuzzy matching and confidence scoring."""

    def __init__(self, match_threshold: float = 0.6) -> None:
        self.match_threshold = match_threshold

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def best_identifier_match(self, candidates: Iterable[str], target: str) -> float:
        return max((self._similarity(candidate, target) for candidate in candidates), default=0.0)

    def build_evidence(
        self, source_type: str, source_id: str, confidence: float, metadata: dict | None = None
    ) -> EvidenceRef:
        return EvidenceRef(
            source_type=source_type,
            source_id=source_id,
            confidence=confidence,
            metadata=metadata or {},
        )

    def resolve_asset(
        self, payload: dict, source_type: str, source_id: str, confidence: float
    ) -> Asset:
        identifiers: list[str] = []
        for key in ("ip", "hostname", "mac"):
            value = payload.get(key)
            if value:
                identifiers.append(str(value))
        evidence = self.build_evidence(
            source_type, source_id, confidence, metadata={"payload": payload}
        )
        metadata = {k: v for k, v in payload.items() if k not in {"ports"}}
        if "ports" in payload:
            metadata["ports"] = payload.get("ports")
        return Asset(
            kind=payload.get("kind", "host"),
            env=payload.get("env"),
            criticality=payload.get("criticality"),
            owner_team=payload.get("owner_team"),
            lifecycle_state=payload.get("status"),
            identifiers=identifiers,
            metadata=metadata,
            evidence=[evidence],
        )

    def resolve_network(
        self, payload: dict, source_type: str, source_id: str, confidence: float
    ) -> NetworkContainer:
        evidence = self.build_evidence(
            source_type, source_id, confidence, metadata={"payload": payload}
        )
        return NetworkContainer(
            cidr=payload["cidr"],
            name=payload.get("name"),
            network_type=payload.get("network_type", "subnet"),
            metadata=payload.get("metadata", {}),
            evidence=[evidence],
        )

    def resolve_identity(
        self, payload: dict, source_type: str, source_id: str, confidence: float
    ) -> Identity:
        evidence = self.build_evidence(
            source_type, source_id, confidence, metadata={"payload": payload}
        )
        return Identity(
            name=payload["name"],
            identity_type=payload.get("identity_type", "user"),
            groups=payload.get("groups", []),
            privileges=payload.get("privileges", []),
            metadata=payload.get("metadata", {}),
            evidence=[evidence],
        )
