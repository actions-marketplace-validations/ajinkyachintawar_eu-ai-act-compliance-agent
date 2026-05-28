from __future__ import annotations

import json
from datetime import datetime, timezone

from openai import OpenAI

from backend.agents.scanner_prompts import (
    DETECT_PATTERNS_SYSTEM,
    DETECT_PATTERNS_USER,
    GENERATE_VIOLATIONS_SYSTEM,
    GENERATE_VIOLATIONS_USER,
)
from backend.agents.scanner_state import ScannerState
from backend.config import GROQ_API_KEY, GROQ_BASE_URL, SCANNER_MODEL
from backend.models.schemas import (
    CodePattern,
    CodeViolation,
    RiskTier,
    ScanReport,
    ViolationSeverity,
)


def _llm() -> OpenAI:
    # Groq: OpenAI-compatible, ~250 tok/s — much faster than NIM for code analysis
    return OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)


def _chat_json(client: OpenAI, system: str, user: str) -> dict:
    response = client.chat.completions.create(
        model=SCANNER_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


# ---------------------------------------------------------------------------
# Node 1 — detect_patterns
# Reads the code and identifies EU AI Act relevant patterns
# ---------------------------------------------------------------------------

def node_detect_patterns(state: ScannerState) -> dict:
    client = _llm()
    raw = _chat_json(
        client,
        DETECT_PATTERNS_SYSTEM,
        DETECT_PATTERNS_USER.format(
            file_name=state["file_name"],
            code=state["code"],
        ),
    )

    patterns = [
        CodePattern(
            pattern_type=p["pattern_type"],
            description=p["description"],
            file_path=p.get("file_path", state["file_name"]),
            line_number=p.get("line_number"),
            code_snippet=p.get("code_snippet") or "",
            eu_ai_act_relevance=p["eu_ai_act_relevance"],
        )
        for p in raw.get("patterns", [])
    ]
    return {"patterns": patterns}


# ---------------------------------------------------------------------------
# Node 2 — generate_violations
# Maps detected patterns to specific EU AI Act violations
# ---------------------------------------------------------------------------

def node_generate_violations(state: ScannerState) -> dict:
    client = _llm()

    # Build a readable summary of detected patterns for the prompt
    patterns_summary = "\n".join(
        f"- [{p.pattern_type}] {p.description} "
        f"(line {p.line_number or 'N/A'}): {p.eu_ai_act_relevance}"
        for p in state["patterns"]
    ) or "No specific EU AI Act patterns detected."

    raw = _chat_json(
        client,
        GENERATE_VIOLATIONS_SYSTEM,
        GENERATE_VIOLATIONS_USER.format(
            system_context=state["system_context"] or "No additional context provided.",
            patterns_summary=patterns_summary,
            file_name=state["file_name"],
            code=state["code"],
        ),
    )

    violations = [
        CodeViolation(
            rule_id=v["rule_id"],
            article=v["article"],
            title=v["title"],
            description=v["description"],
            severity=ViolationSeverity(v["severity"]),
            file_path=v.get("file_path", state["file_name"]),
            line_number=v.get("line_number"),
            code_snippet=v.get("code_snippet"),
            recommendation=v["recommendation"],
        )
        for v in raw.get("violations", [])
    ]

    risk_raw = raw.get("risk_tier_suggestion")
    risk_tier = RiskTier(risk_raw) if risk_raw else None

    return {
        "violations": violations,
        "risk_tier_suggestion": risk_tier,
        "summary": raw.get("summary", ""),
    }


# ---------------------------------------------------------------------------
# Node 3 — assemble_scan_report
# Assembles the final ScanReport (no LLM call)
# ---------------------------------------------------------------------------

def node_assemble_scan_report(state: ScannerState) -> dict:
    violations = state["violations"]

    report = ScanReport(
        file_name=state["file_name"],
        total_lines=len(state["code"].splitlines()),
        patterns_found=state["patterns"],
        violations=violations,
        total_critical=sum(1 for v in violations if v.severity == ViolationSeverity.CRITICAL),
        total_high=sum(1 for v in violations if v.severity == ViolationSeverity.HIGH),
        total_medium=sum(1 for v in violations if v.severity == ViolationSeverity.MEDIUM),
        total_low=sum(1 for v in violations if v.severity == ViolationSeverity.LOW),
        risk_tier_suggestion=state.get("risk_tier_suggestion"),
        summary=state["summary"],
        generated_at=datetime.now(timezone.utc),
    )
    return {"report": report}
