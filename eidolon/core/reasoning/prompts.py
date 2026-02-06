QUERY_PROMPT_TEMPLATE = """
You translate user questions into Cypher queries over an evidence-backed graph.
Use only these labels: Asset, NetworkContainer, Identity, Policy.
Use only known relationships: MEMBER_OF, CAN_REACH, DEPENDS_ON, AUTHENTICATES_TO, GOVERNED_BY.
If you cannot map the request to a safe graph query, return an answer explaining why and omit
graph_query.
Question: {question}
"""

PLAN_PROMPT_TEMPLATE = """
You generate a cautious, low-risk plan for an infrastructure intent.
Return minimal steps, defaulting to read-only analysis unless execution is explicitly required.
Include rollback guidance and risk for each step. Use tool_hint only when necessary.
Intent: {intent}
Target entity: {target}
"""
