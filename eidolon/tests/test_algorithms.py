from __future__ import annotations

from datetime import datetime

from eidolon.core.graph.algorithms import blast_radius
from eidolon.core.models.graph import Edge, Node


def test_blast_radius_traversal(in_memory_repo) -> None:
    root = Node(label="Asset")
    child = Node(label="Asset")
    in_memory_repo.upsert_node(root)
    in_memory_repo.upsert_node(child)
    in_memory_repo.upsert_edge(
        Edge(
            type="CAN_REACH",
            source=root.node_id,
            target=child.node_id,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
    )

    radius = blast_radius(in_memory_repo, [root.node_id], depth=1)
    assert set(radius.affected_nodes) == {root.node_id, child.node_id}
