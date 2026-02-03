from __future__ import annotations

from fastapi.testclient import TestClient

from eidolon.api.app import create_app
from eidolon.api.dependencies import get_entity_resolver, get_graph_repository


def test_collector_scan_route(in_memory_repo, planner_headers) -> None:
    app = create_app()
    app.dependency_overrides[get_graph_repository] = lambda: in_memory_repo
    app.dependency_overrides[get_entity_resolver] = get_entity_resolver
    client = TestClient(app)

    response = client.post("/collector/scan", headers=planner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["events_processed"] >= 0
    assert data["status"] in {"ok", "partial_failure"}
