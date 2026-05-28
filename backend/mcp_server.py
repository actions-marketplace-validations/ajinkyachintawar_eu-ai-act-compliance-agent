from __future__ import annotations

import threading
import time
import uuid
from typing import Literal

from fastmcp import FastMCP

from backend.agents.nodes import (
    extract_fields_from_text,
    node_check_article6,
    node_classify,
    node_retrieve,
    node_check_obligations,
    node_draft_annex_iv,
    node_assemble,
)
from backend.models.schemas import ObligationStatus, RiskTier, Article6Exception, AnnexIVDraft

mcp = FastMCP(
    name="EU AI Act Compliance Classifier",
    instructions=(
        "Use these tools to assess AI systems against the EU AI Act (Regulation 2024/1689).\n\n"
        "WORKFLOW (always follow this order):\n"
        "1. Call start_analysis(description) — returns a job_id immediately.\n"
        "2. Wait ~90 seconds for a full report, or ~60s for a quick classify.\n"
        "3. Call get_result(job_id) to retrieve the finished report.\n\n"
        "Available job types: 'full_report' (~3 min) | 'quick_classify' (~60s)"
    ),
)

# ---------------------------------------------------------------------------
# In-memory job store (persists for the lifetime of the MCP server process)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _new_job(job_type: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "type": job_type,
            "status": "pending",
            "result": None,
            "error": None,
            "started_at": time.time(),
        }
    return job_id


def _set_done(job_id: str, result: str) -> None:
    with _jobs_lock:
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = result


def _set_error(job_id: str, error: str) -> None:
    with _jobs_lock:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = error


# ---------------------------------------------------------------------------
# Pipeline helpers (run in background threads)
# ---------------------------------------------------------------------------

def _format_report(report) -> str:
    cl = report.classification
    ex = report.article6_exception
    ob = report.obligations
    av = report.annex_iv_draft
    sy = report.system

    lines: list[str] = [
        f"# EU AI Act Compliance Report: {sy.name}",
        "",
        "## System Summary",
        f"- **Use case:** {sy.use_case}",
        f"- **Sector:** {sy.sector}",
        f"- **Inputs:** {sy.inputs}",
        f"- **Outputs:** {sy.outputs}",
        f"- **Affected persons:** {sy.affected_persons}",
        f"- **Decision type:** {sy.decision_type}",
        "",
        "## Risk Classification",
        f"**Tier: {cl.tier}** (confidence: {cl.confidence:.0%})",
        "",
        cl.reasoning,
        "",
        f"*Cited articles: {', '.join(cl.cited_articles)}*",
        "",
    ]
    if cl.annex_iii_category:
        lines += [f"*Annex III category: {cl.annex_iii_category}*", ""]

    lines += [
        "## Article 6 Exception",
        f"**Qualifies:** {'Yes' if ex.qualifies else 'No'}",
        "",
        ex.reasoning,
        "",
        "## Obligations Checklist",
        f"**{ob.total_met} MET / {ob.total_not_met} NOT MET / {ob.total_unclear} UNCLEAR**",
        "",
        "| Article | Title | Status | Evidence |",
        "|---------|-------|--------|----------|",
    ]
    for o in ob.obligations:
        icon = {"MET": "✅", "NOT_MET": "❌", "UNCLEAR": "⚠️"}.get(o.status.value, o.status.value)
        evidence = (o.evidence or "—").replace("\n", " ")
        lines.append(f"| {o.article} | {o.title} | {icon} {o.status.value} | {evidence} |")

    lines += [
        "",
        "## Annex IV Technical Documentation Draft",
        "*(Sections marked [INFORMATION REQUIRED] need your input)*",
        "",
        "### System Description",
        av.system_description,
        "",
        "### Intended Purpose",
        av.intended_purpose,
        "",
        "### Performance Metrics",
        av.performance_metrics,
        "",
        "### Risk Management Summary",
        av.risk_management_summary,
        "",
        "### Data Governance Notes",
        av.data_governance_notes,
        "",
        "---",
        f"*Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        f"*{report.disclaimer}*",
    ]
    return "\n".join(lines)


def _pipeline_full(job_id: str, description: str) -> None:
    try:
        system = extract_fields_from_text(description)
        state: dict = {
            "system": system, "context_chunks": [], "classification": None,
            "article6_exception": None, "obligations": None, "annex_iv_draft": None, "report": None,
        }
        state.update(node_retrieve(state))
        state.update(node_classify(state))

        cl = state["classification"]
        is_high_risk = cl.tier == RiskTier.HIGH_RISK

        if is_high_risk:
            state.update(node_check_article6(state))
        else:
            state["article6_exception"] = Article6Exception(
                qualifies=False,
                reasoning="Article 6 exception not applicable for this risk tier.",
                cited_articles=[],
            )

        state.update(node_check_obligations(state))

        if is_high_risk and not state["article6_exception"].qualifies:
            state.update(node_draft_annex_iv(state))
        else:
            state["annex_iv_draft"] = AnnexIVDraft(
                system_description="Not required — system is not classified as high-risk.",
                intended_purpose="N/A", performance_metrics="N/A",
                risk_management_summary="N/A", data_governance_notes="N/A", is_draft=False,
            )

        state.update(node_assemble(state))
        _set_done(job_id, _format_report(state["report"]))
    except Exception as exc:
        _set_error(job_id, str(exc))


def _pipeline_quick(job_id: str, description: str) -> None:
    try:
        system = extract_fields_from_text(description)
        state: dict = {
            "system": system, "context_chunks": [], "classification": None,
            "article6_exception": None, "obligations": None, "annex_iv_draft": None, "report": None,
        }
        state.update(node_retrieve(state))
        state.update(node_classify(state))

        cl = state["classification"]
        lines = [
            f"## Quick Classification: {system.name}",
            "",
            f"**Risk Tier: {cl.tier.value}**  |  Confidence: {cl.confidence:.0%}",
            "",
            f"**Reasoning:** {cl.reasoning}",
            "",
            f"**Cited articles:** {', '.join(cl.cited_articles)}",
        ]

        if cl.tier == RiskTier.HIGH_RISK:
            state.update(node_check_article6(state))
            ex = state["article6_exception"]
            lines += [
                "",
                f"**Article 6 Exception:** {'Qualifies ✅' if ex.qualifies else 'Does not qualify ❌'}",
                ex.reasoning,
            ]

        if cl.annex_iii_category:
            lines += ["", f"**Annex III category:** {cl.annex_iii_category}"]

        _set_done(job_id, "\n".join(lines))
    except Exception as exc:
        _set_error(job_id, str(exc))


# ---------------------------------------------------------------------------
# Tool 1 — Start a full compliance report (returns job_id instantly)
# ---------------------------------------------------------------------------

@mcp.tool()
def start_analysis(description: str, mode: Literal["full_report", "quick_classify"] = "full_report") -> str:
    """
    Start an EU AI Act compliance analysis job and return a job_id immediately.

    The analysis runs in the background. Use get_result(job_id) to retrieve the output.

    Args:
        description: Plain-English description of the AI system — what it does,
                     who it affects, how decisions are made, and what sector it operates in.
        mode:        'full_report' (~3 min) — full obligations checklist + Annex IV draft.
                     'quick_classify' (~60s) — risk tier + Article 6 check only.
    """
    job_id = _new_job(mode)

    target = _pipeline_full if mode == "full_report" else _pipeline_quick
    thread = threading.Thread(target=target, args=(job_id, description), daemon=True)
    thread.start()

    wait_hint = "~3 minutes" if mode == "full_report" else "~60 seconds"
    return (
        f"✅ Analysis started (mode: `{mode}`).\n\n"
        f"**Job ID:** `{job_id}`\n\n"
        f"The pipeline is running in the background. "
        f"Call `get_result(job_id='{job_id}')` in {wait_hint}."
    )


# ---------------------------------------------------------------------------
# Tool 2 — Poll for result
# ---------------------------------------------------------------------------

@mcp.tool()
def get_result(job_id: str) -> str:
    """
    Retrieve the result of a compliance analysis started with start_analysis.

    Returns the finished report, or a status message if still processing.

    Args:
        job_id: The job ID returned by start_analysis.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        return f"❌ No job found with ID `{job_id}`. Check the ID and try again."

    elapsed = time.time() - job["started_at"]

    if job["status"] == "pending":
        wait_hint = max(0, (180 if job["type"] == "full_report" else 60) - elapsed)
        return (
            f"⏳ Still processing… ({elapsed:.0f}s elapsed)\n\n"
            f"Try again in ~{wait_hint:.0f}s."
        )

    if job["status"] == "error":
        with _jobs_lock:
            del _jobs[job_id]
        return f"❌ Analysis failed: {job['error']}"

    # Done — return result and clean up
    result = job["result"]
    with _jobs_lock:
        del _jobs[job_id]
    return result


if __name__ == "__main__":
    mcp.run()
