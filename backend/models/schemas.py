from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Sector(str, Enum):
    HEALTHCARE = "HEALTHCARE"
    EMPLOYMENT = "EMPLOYMENT"
    EDUCATION = "EDUCATION"
    FINANCE = "FINANCE"
    CRITICAL_INFRASTRUCTURE = "CRITICAL_INFRASTRUCTURE"
    LAW_ENFORCEMENT = "LAW_ENFORCEMENT"
    MIGRATION = "MIGRATION"
    DEMOCRATIC_PROCESSES = "DEMOCRATIC_PROCESSES"
    OTHER = "OTHER"


class DecisionType(str, Enum):
    AUTONOMOUS = "AUTONOMOUS"
    ASSISTIVE = "ASSISTIVE"
    INFORMATIONAL = "INFORMATIONAL"


class RiskTier(str, Enum):
    PROHIBITED = "PROHIBITED"
    HIGH_RISK = "HIGH_RISK"
    LIMITED_RISK = "LIMITED_RISK"
    MINIMAL_RISK = "MINIMAL_RISK"


class ObligationStatus(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    UNCLEAR = "UNCLEAR"


class SystemDescription(BaseModel):
    name: str
    use_case: str
    sector: Sector
    inputs: str
    outputs: str
    affected_persons: str
    decision_type: DecisionType
    existing_practices: Optional[str] = None


class ClassificationResult(BaseModel):
    tier: RiskTier
    confidence: float = Field(..., ge=0.0, le=1.0)
    annex_iii_category: Optional[str] = None
    cited_articles: list[str] = Field(default_factory=list)
    reasoning: str


class Article6Exception(BaseModel):
    qualifies: bool
    reasoning: str
    cited_articles: list[str] = Field(default_factory=list)


class Obligation(BaseModel):
    article: str
    title: str
    description: str
    status: ObligationStatus
    evidence: Optional[str] = None


class ObligationsChecklist(BaseModel):
    obligations: list[Obligation] = Field(default_factory=list)
    total_met: int = 0
    total_not_met: int = 0
    total_unclear: int = 0


class AnnexIVDraft(BaseModel):
    system_description: str
    intended_purpose: str
    performance_metrics: str
    risk_management_summary: str
    data_governance_notes: str
    is_draft: bool = True


# ---------------------------------------------------------------------------
# Code Scanner schemas
# ---------------------------------------------------------------------------

class ViolationSeverity(str, Enum):
    CRITICAL = "CRITICAL"   # Required safeguard completely absent in a high-risk system
    HIGH = "HIGH"           # Safeguard appears to be missing
    MEDIUM = "MEDIUM"       # Safeguard present but incomplete
    LOW = "LOW"             # Best practice not followed


class CodePattern(BaseModel):
    """A single EU AI Act-relevant pattern detected in source code."""
    pattern_type: str                    # e.g. "model_inference", "automated_decision"
    description: str
    file_path: str
    line_number: Optional[int] = None
    code_snippet: str = ""
    eu_ai_act_relevance: str


class CodeViolation(BaseModel):
    """A specific EU AI Act compliance violation found in source code."""
    rule_id: str                         # e.g. "ART12-001"
    article: str                         # e.g. "Article 12"
    title: str
    description: str
    severity: ViolationSeverity
    file_path: str
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    recommendation: str


class ScanRequest(BaseModel):
    code: str
    file_name: str = "uploaded_file.py"
    system_context: Optional[str] = None  # optional plain-English context from /describe


class ScanReport(BaseModel):
    file_name: str
    total_lines: int
    patterns_found: list[CodePattern] = Field(default_factory=list)
    violations: list[CodeViolation] = Field(default_factory=list)
    total_critical: int = 0
    total_high: int = 0
    total_medium: int = 0
    total_low: int = 0
    risk_tier_suggestion: Optional[RiskTier] = None
    summary: str
    disclaimer: str = (
        "This scan identifies potential EU AI Act compliance gaps in source code. "
        "It does not constitute legal advice. Review findings with a qualified legal professional."
    )
    generated_at: datetime


class ComplianceReport(BaseModel):
    system: SystemDescription
    classification: ClassificationResult
    article6_exception: Article6Exception
    obligations: ObligationsChecklist
    annex_iv_draft: AnnexIVDraft
    disclaimer: str = (
        "This report is a preliminary screening tool only. "
        "It does not constitute legal advice. Consult a qualified legal professional "
        "before submitting to a notified body or making compliance decisions."
    )
    generated_at: datetime
