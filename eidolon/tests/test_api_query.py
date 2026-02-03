from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from eidolon.api.app import create_app
from eidolon.api.dependencies import get_graph_repository
from eidolon.core.models.graph import Edge, Node


def test_query_path_endpoint(in_memory_repo, viewer_headers) -> None:
    app = create_app()
    app.dependency_overrides[get_graph_repository] = lambda: in_memory_repo
    client = TestClient(app)

    source = Node(label="Asset")
    target = Node(label="Asset")
    in_memory_repo.upsert_node(source)
    in_memory_repo.upsert_node(target)
    in_memory_repo.upsert_edge(
        Edge(
            type="CAN_REACH",
            source=source.node_id,
            target=target.node_id,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
    )

    response = client.post(
        "/query/",
        json={
            "question": "find path",
            "source_id": str(source.node_id),
            "target_id": str(target.node_id),
            "max_depth": 3,
        },
        headers=viewer_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Path search completed."
    assert data["paths"][0]["nodes"][0] == str(source.node_id)


def test_nl_query_generates_cypher(in_memory_repo, viewer_headers) -> None:
    app = create_app()
    app.dependency_overrides[get_graph_repository] = lambda: in_memory_repo
    client = TestClient(app)

    response = client.post(
        "/query/",
        json={"question": "list assets in network 10.0.0.0/24"},
        headers=viewer_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["graph_query"] is not None
    assert "network" in data["graph_query"]["parameters"]
