from __future__ import annotations

from datetime import datetime

from eidolon.core.models.graph import Edge, Node


def test_upsert_and_find_paths(in_memory_repo) -> None:
    source = Node(label="Asset")
    target = Node(label="Asset")
    in_memory_repo.upsert_node(source)
    in_memory_repo.upsert_node(target)

    edge = Edge(
        type="CAN_REACH",
        source=source.node_id,
        target=target.node_id,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    in_memory_repo.upsert_edge(edge)

    paths = in_memory_repo.find_paths(source.node_id, target.node_id)
    assert len(paths) == 1
    assert paths[0].nodes == [source.node_id, target.node_id]
    assert paths[0].edges == ["CAN_REACH"]
