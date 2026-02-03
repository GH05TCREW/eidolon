from __future__ import annotations

from fastapi.testclient import TestClient

from eidolon.api.app import create_app
from eidolon.api.dependencies import get_graph_repository
from eidolon.core.models.graph import Edge, Node


def test_graph_assets_endpoints(in_memory_repo, viewer_headers) -> None:
    app = create_app()
    app.dependency_overrides[get_graph_repository] = lambda: in_memory_repo
    client = TestClient(app)

    asset = Node(label="Asset")
    in_memory_repo.upsert_node(asset)

    resp = client.get(f"/graph/assets/{asset.node_id}", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["label"] == "Asset"

    resp_list = client.get("/graph/assets", headers=viewer_headers)
    assert resp_list.status_code == 200
    assert len(resp_list.json()) >= 1


def test_graph_paths_endpoint(in_memory_repo, viewer_headers) -> None:
    app = create_app()
    app.dependency_overrides[get_graph_repository] = lambda: in_memory_repo
    client = TestClient(app)

    a = Node(label="Asset")
    b = Node(label="Asset")
    in_memory_repo.upsert_node(a)
    in_memory_repo.upsert_node(b)
    in_memory_repo.upsert_edge(Edge(type="CAN_REACH", source=a.node_id, target=b.node_id))

    resp = client.get(
        "/graph/paths",
        params={"source_id": str(a.node_id), "target_id": str(b.node_id), "max_depth": 3},
        headers=viewer_headers,
    )
    assert resp.status_code == 200
    paths = resp.json()
    assert paths and paths[0]["nodes"][0] == str(a.node_id)
