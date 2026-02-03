from __future__ import annotations

from typing import Any

from eidolon.core.graph.repository import GraphRepository
from eidolon.runtime.tools.base import Tool


class GraphQueryTool(Tool):
    name = "graph_query"
    description = """Execute Cypher queries against the Eidolon infrastructure graph (Neo4j 5.x).

CRITICAL syntax requirements:
- Use `n.property IS NOT NULL` instead of `exists(n.property)` (deprecated)
- Available labels: NetworkContainer, Asset, Identity, Policy
- Common patterns:
  * List networks: MATCH (n:NetworkContainer) WHERE n.cidr IS NOT NULL RETURN n
  * Find assets: MATCH (a:Asset) WHERE a.asset_id IS NOT NULL RETURN a
  * Get relationships: MATCH (a)-[r]->(b) RETURN a, type(r), b"""
    sandbox_execution = False

    def __init__(self, repository: GraphRepository) -> None:
        self.repository = repository

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cypher": {
                    "type": "string",
                    "description": "The Cypher query to execute against the Neo4j graph",
                },
                "parameters": {
                    "type": "object",
                    "description": "Optional parameters for the Cypher query",
                },
            },
            "required": ["cypher"],
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        cypher = payload.get("cypher")
        parameters = payload.get("parameters") or {}
        if not cypher:
            return {"error": "cypher is required"}
        records = list(self.repository.run_cypher(cypher, parameters))
        return {"records": records}
