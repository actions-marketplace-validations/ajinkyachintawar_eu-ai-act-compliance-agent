from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict

from backend.models.schemas import CodePattern, CodeViolation, RiskTier, ScanReport


class ScannerState(TypedDict):
    file_name: str
    code: str
    system_context: str                       # plain-English context (may be empty)
    patterns: list[CodePattern]
    violations: list[CodeViolation]
    risk_tier_suggestion: Optional[RiskTier]
    summary: str
    report: Optional[ScanReport]
