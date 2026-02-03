from __future__ import annotations

from eidolon.core.reasoning.entity import EntityResolver


def test_resolve_asset() -> None:
    resolver = EntityResolver()
    payload = {"ip": "10.0.0.5", "hostname": "app-server", "env": "prod", "criticality": "high"}
    asset = resolver.resolve_asset(
        payload, source_type="network", source_id="scan-1", confidence=0.8
    )

    assert "10.0.0.5" in asset.identifiers
    assert asset.evidence[0].source_type == "network"
    assert asset.kind == "host"
