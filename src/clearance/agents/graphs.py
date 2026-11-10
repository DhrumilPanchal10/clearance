"""LangGraph sub-graphs (plan T5.8).

assess_graph: intake -> (evidence ∥ policy) -> criteria. The evidence and policy
nodes fan out from intake and fan in at criteria, which LangGraph runs
concurrently; the state reducers merge their writes.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from clearance.agents.state import CaseState

NodeFn = Any  # async (state) -> state-update dict


def build_assess_graph(intake: NodeFn, policy: NodeFn, evidence: NodeFn, criteria: NodeFn) -> Any:
    g: StateGraph[CaseState] = StateGraph(CaseState)
    g.add_node("intake", intake)
    g.add_node("policy", policy)
    g.add_node("evidence", evidence)
    g.add_node("criteria", criteria)

    g.add_edge(START, "intake")
    # Fan out: evidence ∥ policy.
    g.add_edge("intake", "policy")
    g.add_edge("intake", "evidence")
    # Fan in: criteria waits for both.
    g.add_edge("policy", "criteria")
    g.add_edge("evidence", "criteria")
    g.add_edge("criteria", END)

    return g.compile()
