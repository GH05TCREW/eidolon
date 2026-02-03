from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from eidolon.api.dependencies import (
    get_graph_repository,
    get_llm_client,
    require_roles,
)
from eidolon.api.middleware.auth import IdentityContext
from eidolon.core.graph.repository import GraphRepository
from eidolon.core.models.graph import GraphPath
from eidolon.core.models.plan import GraphQuery
from eidolon.core.reasoning.llm import LiteLLMClient
from eidolon.core.reasoning.prompts import QUERY_PROMPT_TEMPLATE


class QueryRequest(BaseModel):
    question: str = Field(description="Natural language query")
    source_id: UUID | None = Field(
        default=None, description="Optional source node for path queries"
    )
    target_id: UUID | None = Field(
        default=None, description="Optional target node for path queries"
    )
    max_depth: int = Field(default=4, ge=1, le=8)


class QueryResponse(BaseModel):
    answer: str
    paths: list[GraphPath] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)
    graph_query: GraphQuery | None = None
    records: list[dict] = Field(default_factory=list)


class NLQueryPlan(BaseModel):
    answer: str
    graph_query: GraphQuery | None = None
    citations: list[dict] = Field(default_factory=list)


router = APIRouter(prefix="/query", tags=["query"])
_GRAPH_REPOSITORY = Depends(get_graph_repository)
_LLM_CLIENT = Depends(get_llm_client)
_VIEWER_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))


class NaturalLanguageQueryInterpreter:
    """
    Minimal rule-based interpreter to keep queries deterministic until the NL->Cypher LLM layer
    is added.
    """

    def __init__(
        self, repository: GraphRepository, llm_client: LiteLLMClient | None = None
    ) -> None:
        self.repository = repository
        self.llm_client = llm_client

    def _parse_rules(self, question: str) -> NLQueryPlan:
        q = question.lower()

        path_match = re.search(r"from\s+(?P<src>[\w\.-]+)\s+to\s+(?P<dst>[\w\.-]+)", q)
        if "path" in q and path_match:
            src = path_match.group("src")
            dst = path_match.group("dst")
            cypher = (
                "MATCH (src:Asset)-[r:CAN_REACH*1..4]->(dst:Asset) "
                "WHERE ($src IN src.identifiers OR src.node_id = $src) "
                "AND ($dst IN dst.identifiers OR dst.node_id = $dst) "
                "RETURN src, dst, r LIMIT 10"
            )
            return NLQueryPlan(
                answer=f"Finding paths from {src} to {dst}.",
                graph_query=GraphQuery(
                    cypher=cypher,
                    parameters={"src": src, "dst": dst},
                ),
            )

        assets_in_network = re.search(r"assets? in network\s+(?P<net>[\w\./-]+)", q)
        if assets_in_network:
            network = assets_in_network.group("net")
            cypher = (
                "MATCH (a:Asset)-[:MEMBER_OF]->(n:NetworkContainer) "
                "WHERE n.cidr = $network OR n.name = $network "
                "RETURN a LIMIT 100"
            )
            return NLQueryPlan(
                answer=f"Listing assets in network {network}.",
                graph_query=GraphQuery(cypher=cypher, parameters={"network": network}),
            )

        if "policy" in q and ("govern" in q or "attached" in q):
            cypher = "MATCH (a:Asset)-[:GOVERNED_BY]->(p:Policy) " "RETURN a, p LIMIT 100"
            return NLQueryPlan(
                answer="Fetching governed assets and their policies.",
                graph_query=GraphQuery(cypher=cypher, parameters={}),
            )

        return NLQueryPlan(
            answer="Query interpreted but no matching pattern; no graph query executed."
        )

    def parse(self, question: str) -> NLQueryPlan:
        plan = self._parse_rules(question)
        if plan.graph_query or not self.llm_client or not self.llm_client.is_available():
            return plan
        prompt = QUERY_PROMPT_TEMPLATE.format(question=question)
        try:
            llm_plan = self.llm_client.generate_structured(prompt, NLQueryPlan)
        except (RuntimeError, TypeError, ValueError):
            return plan
        return llm_plan if llm_plan.answer else plan


@router.post("/", response_model=QueryResponse)
def handle_query(
    request: QueryRequest,
    repository: GraphRepository = _GRAPH_REPOSITORY,
    llm_client: LiteLLMClient = _LLM_CLIENT,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> QueryResponse:
    if request.source_id and request.target_id:
        paths = repository.find_paths(request.source_id, request.target_id, request.max_depth)
        return QueryResponse(
            answer="Path search completed.",
            paths=paths,
            citations=[],
        )
    if not request.question:
        raise HTTPException(status_code=400, detail="question is required")

    interpreter = NaturalLanguageQueryInterpreter(repository, llm_client=llm_client)
    plan = interpreter.parse(request.question)
    records: list[dict] = []
    if plan.graph_query:
        records = list(repository.run_cypher(plan.graph_query.cypher, plan.graph_query.parameters))

    return QueryResponse(
        answer=plan.answer,
        paths=[],
        citations=plan.citations,
        graph_query=plan.graph_query,
        records=records,
    )
