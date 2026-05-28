from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict

from backend.models.schemas import (
    AnnexIVDraft,
    Article6Exception,
    ClassificationResult,
    ComplianceReport,
    ObligationsChecklist,
    SystemDescription,
)


class AgentState(TypedDict):
    system: SystemDescription
    context_chunks: list[dict]
    classification: Optional[ClassificationResult]
    article6_exception: Optional[Article6Exception]
    obligations: Optional[ObligationsChecklist]
    annex_iv_draft: Optional[AnnexIVDraft]
    report: Optional[ComplianceReport]
