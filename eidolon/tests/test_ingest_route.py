from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from eidolon.api.app import create_app
from eidolon.api.dependencies import get_entity_resolver, get_graph_repository
from eidolon.core.models.event import CollectorEvent


def test_ingest_events(in_memory_repo, executor_headers) -> None:
    app = create_app()
    app.dependency_overrides[get_graph_repository] = lambda: in_memory_repo
    app.dependency_overrides[get_entity_resolver] = get_entity_resolver
    client = TestClient(app)

    event = CollectorEvent(
        source_type="network",
        source_id="ingest-test",
        entity_type="Asset",
        payload={"ip": "10.0.0.10", "cidr": "10.0.0.0/24"},
        collected_at=datetime.utcnow(),
    )

    response = client.post(
        "/ingest/events",
        json=[event.model_dump(mode="json")],
        headers=executor_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert len(in_memory_repo.nodes) == 2
    assert any(edge.type == "MEMBER_OF" for edge in in_memory_repo.edges)
