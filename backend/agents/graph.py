from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.nodes import (
    node_assemble,
    node_check_article6,
    node_check_obligations,
    node_classify,
    node_draft_annex_iv,
    node_retrieve,
)
from backend.agents.state import AgentState
from backend.models.schemas import RiskTier


def _route_after_classify(state: AgentState) -> str:
    tier = state["classification"].tier
    if tier == RiskTier.HIGH_RISK:
        return "check_article6"
    return "check_obligations"


def _route_after_article6(state: AgentState) -> str:
    # If the Art 6 exception applies, treat as LIMITED_RISK — skip Annex IV
    exception = state.get("article6_exception")
    if exception and exception.qualifies:
        return "check_obligations"
    return "check_obligations"  # always goes to obligations; Annex IV is gated by tier


def _route_after_obligations(state: AgentState) -> str:
    tier = state["classification"].tier
    exception = state.get("article6_exception")
    exception_applies = exception is not None and exception.qualifies

    if tier == RiskTier.HIGH_RISK and not exception_applies:
        return "draft_annex_iv"
    return "assemble"


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("retrieve", node_retrieve)
    g.add_node("classify", node_classify)
    g.add_node("check_article6", node_check_article6)
    g.add_node("check_obligations", node_check_obligations)
    g.add_node("draft_annex_iv", node_draft_annex_iv)
    g.add_node("assemble", node_assemble)

    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "classify")

    g.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"check_article6": "check_article6", "check_obligations": "check_obligations"},
    )

    g.add_edge("check_article6", "check_obligations")

    g.add_conditional_edges(
        "check_obligations",
        _route_after_obligations,
        {"draft_annex_iv": "draft_annex_iv", "assemble": "assemble"},
    )

    g.add_edge("draft_annex_iv", "assemble")
    g.add_edge("assemble", END)

    return g


# Compiled graph — import and call .invoke() from the API layer
compiled_graph = build_graph().compile()
