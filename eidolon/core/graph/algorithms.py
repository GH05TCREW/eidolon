from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from uuid import UUID

from neo4j.exceptions import Neo4jError

from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.plan import BlastRadius


def blast_radius(
    repository: GraphRepository, targets: Sequence[UUID], depth: int = 2
) -> BlastRadius:
    """
    Estimate blast radius by traversing outbound relationships up to the given depth.

    This uses repository neighbor lookups to avoid binding to a specific graph backend.
    """
    visited: set[UUID] = set()
    queue: deque[tuple[UUID, int]] = deque([(target, 0) for target in targets])
    paths = []

    while queue:
        node_id, level = queue.popleft()
        if node_id in visited or level > depth:
            continue
        visited.add(node_id)
        neighbors = repository.get_neighbors(node_id)
        for neighbor in neighbors:
            if neighbor not in visited and level + 1 <= depth:
                queue.append((neighbor, level + 1))

    return BlastRadius(affected_nodes=list(visited), paths=paths, score=float(len(visited)))


def min_cut_edges(repository: GraphRepository, source: UUID, target: UUID) -> list[dict]:
    """
    Wrapper for computing min-cut edges between two nodes.

    For Neo4j, this attempts to call GDS. Implementations without GDS support can
    override run_cypher to provide results or return an empty list.
    """
    cypher = """
    CALL gds.alpha.minCut.stream({
      nodeProjection: '*',
      relationshipProjection: '*'
    })
    YIELD sourceNodeId, targetNodeId, cutCost
    RETURN gds.util.asNode(sourceNodeId).node_id AS source_id,
           gds.util.asNode(targetNodeId).node_id AS target_id,
           cutCost
    """
    try:
        result = list(repository.run_cypher(cypher))
    except (Neo4jError, RuntimeError, TypeError, ValueError):
        result = []
    return result
