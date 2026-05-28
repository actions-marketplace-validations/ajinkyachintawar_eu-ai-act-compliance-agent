from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.scanner_nodes import (
    node_assemble_scan_report,
    node_detect_patterns,
    node_generate_violations,
)
from backend.agents.scanner_state import ScannerState


def build_scanner_graph() -> StateGraph:
    g = StateGraph(ScannerState)

    g.add_node("detect_patterns", node_detect_patterns)
    g.add_node("generate_violations", node_generate_violations)
    g.add_node("assemble_report", node_assemble_scan_report)

    g.add_edge(START, "detect_patterns")
    g.add_edge("detect_patterns", "generate_violations")
    g.add_edge("generate_violations", "assemble_report")
    g.add_edge("assemble_report", END)

    return g


compiled_scanner = build_scanner_graph().compile()
