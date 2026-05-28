from __future__ import annotations

import json
from datetime import datetime, timezone

from openai import OpenAI

from backend.agents.prompts import (
    ANNEX_IV_SYSTEM,
    ANNEX_IV_USER,
    ARTICLE6_SYSTEM,
    ARTICLE6_USER,
    CLASSIFY_SYSTEM,
    CLASSIFY_USER,
    EXTRACT_FIELDS_SYSTEM,
    EXTRACT_FIELDS_USER,
    OBLIGATIONS_SYSTEM,
    OBLIGATIONS_USER,
)
from backend.agents.state import AgentState
from backend.config import COMPLIANCE_MODEL, GROQ_API_KEY, GROQ_BASE_URL
from backend.models.schemas import (
    AnnexIVDraft,
    Article6Exception,
    ClassificationResult,
    ComplianceReport,
    Obligation,
    ObligationStatus,
    ObligationsChecklist,
    RiskTier,
    SystemDescription,
)
from backend.rag.retriever import format_context, retrieve


def _llm() -> OpenAI:
    return OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)


def _system_summary(state: AgentState) -> str:
    s = state["system"]
    return (
        f"Name: {s.name}\n"
        f"Use case: {s.use_case}\n"
        f"Sector: {s.sector}\n"
        f"Inputs: {s.inputs}\n"
        f"Outputs: {s.outputs}\n"
        f"Affected persons: {s.affected_persons}\n"
        f"Decision type: {s.decision_type}\n"
        f"Existing practices: {s.existing_practices or 'None provided'}"
    )


def _chat_json(client: OpenAI, system: str, user: str) -> dict:
    response = client.chat.completions.create(
        model=COMPLIANCE_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


# ---------------------------------------------------------------------------
# Pre-processing — extract structured fields from free-text description
# ---------------------------------------------------------------------------

_SECTOR_ALIASES: dict[str, str] = {
    "financial": "FINANCE",
    "financial services": "FINANCE",
    "banking": "FINANCE",
    "insurance": "FINANCE",
    "e-commerce": "OTHER",
    "retail": "OTHER",
    "hr": "EMPLOYMENT",
    "human resources": "EMPLOYMENT",
    "autonomous": "AUTONOMOUS",  # guard for decision_type bleed-through
}

_DECISION_TYPE_ALIASES: dict[str, str] = {
    "advisory": "ASSISTIVE",
    "human_in_the_loop": "ASSISTIVE",
    "human-in-the-loop": "ASSISTIVE",
    "semi-autonomous": "ASSISTIVE",
    "automated": "AUTONOMOUS",
}


def _normalise(value: str, aliases: dict[str, str]) -> str:
    return aliases.get(value.strip().lower(), value.strip().upper())


def extract_fields_from_text(description: str) -> SystemDescription:
    """Convert a plain-English AI system description into a structured SystemDescription."""
    client = _llm()
    raw = _chat_json(client, EXTRACT_FIELDS_SYSTEM, EXTRACT_FIELDS_USER.format(description=description))
    return SystemDescription(
        name=raw["name"],
        use_case=raw["use_case"],
        sector=_normalise(raw["sector"], _SECTOR_ALIASES),
        inputs=raw["inputs"],
        outputs=raw["outputs"],
        affected_persons=raw["affected_persons"],
        decision_type=_normalise(raw["decision_type"], _DECISION_TYPE_ALIASES),
        existing_practices=raw.get("existing_practices"),
    )


# ---------------------------------------------------------------------------
# Node 1 — retrieve
# ---------------------------------------------------------------------------

def node_retrieve(state: AgentState) -> dict:
    s = state["system"]
    query = f"{s.use_case} {s.sector} {s.inputs} {s.outputs} {s.affected_persons}"
    chunks = retrieve(query, k=8)
    return {"context_chunks": chunks}


# ---------------------------------------------------------------------------
# Node 2 — classify
# ---------------------------------------------------------------------------

def node_classify(state: AgentState) -> dict:
    s = state["system"]
    context = format_context(state["context_chunks"])
    client = _llm()

    raw = _chat_json(
        client,
        CLASSIFY_SYSTEM,
        CLASSIFY_USER.format(
            name=s.name,
            use_case=s.use_case,
            sector=s.sector,
            inputs=s.inputs,
            outputs=s.outputs,
            affected_persons=s.affected_persons,
            decision_type=s.decision_type,
            existing_practices=s.existing_practices or "None provided",
            context=context,
        ),
    )

    classification = ClassificationResult(
        tier=RiskTier(raw["tier"]),
        confidence=float(raw["confidence"]),
        annex_iii_category=raw.get("annex_iii_category"),
        cited_articles=raw.get("cited_articles", []),
        reasoning=raw["reasoning"],
    )
    return {"classification": classification}


# ---------------------------------------------------------------------------
# Node 3 — check_article6_exception (HIGH_RISK only)
# ---------------------------------------------------------------------------

def node_check_article6(state: AgentState) -> dict:
    context = format_context(state["context_chunks"])
    client = _llm()

    raw = _chat_json(
        client,
        ARTICLE6_SYSTEM,
        ARTICLE6_USER.format(
            system_summary=_system_summary(state),
            context=context,
        ),
    )

    exception = Article6Exception(
        qualifies=bool(raw["qualifies"]),
        reasoning=raw["reasoning"],
        cited_articles=raw.get("cited_articles", []),
    )
    return {"article6_exception": exception}


# ---------------------------------------------------------------------------
# Node 4 — check_obligations
# ---------------------------------------------------------------------------

def node_check_obligations(state: AgentState) -> dict:
    tier = state["classification"].tier
    context = format_context(state["context_chunks"])
    client = _llm()

    raw = _chat_json(
        client,
        OBLIGATIONS_SYSTEM,
        OBLIGATIONS_USER.format(
            system_summary=_system_summary(state),
            tier=tier.value,
            context=context,
        ),
    )

    obligations = [
        Obligation(
            article=o["article"],
            title=o["title"],
            description=o["description"],
            status=ObligationStatus(o["status"]),
            evidence=o.get("evidence"),
        )
        for o in raw.get("obligations", [])
    ]
    checklist = ObligationsChecklist(
        obligations=obligations,
        total_met=sum(1 for o in obligations if o.status == ObligationStatus.MET),
        total_not_met=sum(1 for o in obligations if o.status == ObligationStatus.NOT_MET),
        total_unclear=sum(1 for o in obligations if o.status == ObligationStatus.UNCLEAR),
    )
    return {"obligations": checklist}


# ---------------------------------------------------------------------------
# Node 5 — draft_annex_iv (HIGH_RISK only)
# ---------------------------------------------------------------------------

def node_draft_annex_iv(state: AgentState) -> dict:
    classification = state["classification"]
    context = format_context(state["context_chunks"])
    client = _llm()

    raw = _chat_json(
        client,
        ANNEX_IV_SYSTEM,
        ANNEX_IV_USER.format(
            system_summary=_system_summary(state),
            tier=classification.tier.value,
            annex_iii_category=classification.annex_iii_category or "N/A",
            context=context,
        ),
    )

    draft = AnnexIVDraft(
        system_description=raw["system_description"],
        intended_purpose=raw["intended_purpose"],
        performance_metrics=raw["performance_metrics"],
        risk_management_summary=raw["risk_management_summary"],
        data_governance_notes=raw["data_governance_notes"],
        is_draft=True,
    )
    return {"annex_iv_draft": draft}


# ---------------------------------------------------------------------------
# Node 6 — assemble_report
# ---------------------------------------------------------------------------

def node_assemble(state: AgentState) -> dict:
    classification = state["classification"]
    tier = classification.tier

    # For non-high-risk tiers, Article 6 exception is not applicable
    article6 = state.get("article6_exception") or Article6Exception(
        qualifies=False,
        reasoning="Article 6 exception check not applicable for this risk tier.",
        cited_articles=[],
    )

    # For non-high-risk tiers, Annex IV draft is not required
    annex_iv = state.get("annex_iv_draft") or AnnexIVDraft(
        system_description="Not required — system is not classified as high-risk.",
        intended_purpose="N/A",
        performance_metrics="N/A",
        risk_management_summary="N/A",
        data_governance_notes="N/A",
        is_draft=False,
    )

    report = ComplianceReport(
        system=state["system"],
        classification=classification,
        article6_exception=article6,
        obligations=state["obligations"],
        annex_iv_draft=annex_iv,
        generated_at=datetime.now(timezone.utc),
    )
    # Return as dict so FastAPI can serialise it; graph stores it on state key "report"
    return {"report": report}
