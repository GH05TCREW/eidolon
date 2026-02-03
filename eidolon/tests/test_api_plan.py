from __future__ import annotations

from fastapi.testclient import TestClient

from eidolon.api.app import create_app
from eidolon.api.dependencies import get_graph_repository
from eidolon.tests.conftest import InMemoryGraphRepository


def test_plan_endpoint_generates_steps(planner_headers) -> None:
    app = create_app()
    app.dependency_overrides[get_graph_repository] = InMemoryGraphRepository
    client = TestClient(app)

    payload = {
        "intent": "Explain how to isolate subnet X safely.",
        "target": {
            "entity_type": "NetworkContainer",
            "display_name": "subnet-x",
            "confidence": 0.7,
        },
    }

    response = client.post("/plan/", json=payload, headers=planner_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["steps"]
    assert body["decision"]["effect"] in {"allow", "needs_approval"}


def test_execute_requires_token_for_non_dry_run(executor_headers) -> None:
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/plan/execute",
        json={
            "dry_run": False,
            "requires_approval": True,
            "steps": [],
        },
        headers=executor_headers,
    )
    assert response.status_code == 403
