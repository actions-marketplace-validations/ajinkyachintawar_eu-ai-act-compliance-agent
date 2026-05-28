#!/usr/bin/env python3
"""
EU AI Act Compliance Scanner — GitHub Actions entrypoint.

Standalone scanner: only requires `openai`. No LangGraph or FastAPI needed.
Reads GROQ_API_KEY, SCAN_FILES, SYSTEM_CONTEXT, FAIL_ON from environment.
Writes a markdown summary to $GITHUB_STEP_SUMMARY and sets action outputs.
Exits 1 if violations at/above FAIL_ON severity are found.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
SCANNER_MODEL = "llama-3.3-70b-versatile"

SCAN_FILES = os.environ.get("SCAN_FILES", "**/*.py")
SYSTEM_CONTEXT = os.environ.get("SYSTEM_CONTEXT", "")
FAIL_ON = os.environ.get("FAIL_ON", "CRITICAL").upper()
GITHUB_STEP_SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")
GITHUB_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")

SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# ---------------------------------------------------------------------------
# Prompts (self-contained — no import from backend)
# ---------------------------------------------------------------------------

DETECT_SYSTEM = """\
You are an EU AI Act code compliance analyzer. Analyze the provided Python source code and identify \
patterns relevant to EU AI Act obligations.

Pattern types to look for:
- model_inference       : ML model loading, prediction, inference calls
- automated_decision    : Score thresholds, accept/reject logic, ranking/sorting of people
- personal_data         : Processing names, emails, IDs, biometrics, health, financial data
- logging_audit         : Logging calls, audit trails (present OR notably absent)
- human_oversight       : Manual review gates, override/escalation mechanisms
- bias_fairness         : Fairness metrics, bias detection or mitigation
- error_handling        : Try/catch blocks, fallback logic, graceful degradation
- data_validation       : Input validation, data quality checks
- transparency          : Disclosures to users about AI involvement

Respond with JSON only:
{"patterns": [{"pattern_type": "<type>", "description": "<what found>", "line_number": <int|null>, "code_snippet": "<max 2 lines|null>", "eu_ai_act_relevance": "<why it matters>"}]}
"""

VIOLATIONS_SYSTEM = """\
You are an EU AI Act compliance auditor reviewing Python source code. Generate specific violation findings.

Obligations (apply to HIGH_RISK unless stated):
- Article 9  : Risk management — evidence of risk assessment process
- Article 10 : Data governance — bias checks, data quality validation
- Article 12 : Automatic logging — inputs/outputs/timestamps must be logged
- Article 13 : Transparency — users informed they interact with AI
- Article 14 : Human oversight — humans can review, override, intervene
- Article 15 : Accuracy/robustness — accuracy tracked, fallback on failure
- Article 50 : AI self-identification (ALL tiers — chatbots must identify as AI)

Severity:
- CRITICAL : Required safeguard completely absent in a high-risk system
- HIGH     : Safeguard clearly missing
- MEDIUM   : Safeguard present but incomplete
- LOW      : Best practice not followed

Only flag violations clearly evidenced by (or clearly absent from) the code.

Respond with JSON only:
{"violations": [{"rule_id": "<ART12-001>", "article": "<Article X>", "title": "<max 6 words>", "description": "<what is missing>", "severity": "CRITICAL|HIGH|MEDIUM|LOW", "line_number": <int|null>, "code_snippet": "<code or null>", "recommendation": "<specific fix>"}], "risk_tier_suggestion": "PROHIBITED|HIGH_RISK|LIMITED_RISK|MINIMAL_RISK", "summary": "<2 sentences>"}
"""


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _client() -> OpenAI:
    if not GROQ_API_KEY:
        print("::error::GROQ_API_KEY is not set. Add it as a repository secret.")
        sys.exit(1)
    return OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)


def _chat_json(client: OpenAI, system: str, user: str) -> dict:
    resp = client.chat.completions.create(
        model=SCANNER_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

# Files to always skip — not AI system code
_SKIP_PATTERNS = {
    "setup.py", "conftest.py", "scan_action.py",
    "**/test_*.py", "**/tests/**", "**/__init__.py",
    "**/migrations/**", "**/venv/**", "**/.venv/**",
}

def _should_skip(path: str) -> bool:
    p = Path(path)
    for pattern in _SKIP_PATTERNS:
        if p.match(pattern):
            return True
    return False


def _discover_files() -> list[str]:
    patterns = SCAN_FILES.split()
    found: list[str] = []
    for pattern in patterns:
        for match in glob.glob(pattern, recursive=True):
            if match.endswith(".py") and not _should_skip(match):
                found.append(match)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Per-file scan
# ---------------------------------------------------------------------------

def scan_file(client: OpenAI, file_path: str) -> dict:
    code = Path(file_path).read_text(encoding="utf-8", errors="replace")
    if not code.strip():
        return {"patterns": [], "violations": [], "risk_tier_suggestion": None, "summary": "Empty file."}

    # Truncate very large files to avoid token limits
    lines = code.splitlines()
    if len(lines) > 300:
        code = "\n".join(lines[:300]) + f"\n# ... truncated at 300/{len(lines)} lines"

    detect_raw = _chat_json(
        client, DETECT_SYSTEM,
        f"File: {file_path}\n\n```python\n{code}\n```"
    )
    patterns = detect_raw.get("patterns", [])

    patterns_summary = "\n".join(
        f"- [{p.get('pattern_type')}] {p.get('description')} (line {p.get('line_number', 'N/A')})"
        for p in patterns
    ) or "No EU AI Act relevant patterns detected."

    violations_raw = _chat_json(
        client, VIOLATIONS_SYSTEM,
        f"System context: {SYSTEM_CONTEXT or 'Not provided'}\n\n"
        f"Patterns detected:\n{patterns_summary}\n\n"
        f"File: {file_path}\n```python\n{code}\n```"
    )

    return {
        "file": file_path,
        "patterns": patterns,
        "violations": violations_raw.get("violations", []),
        "risk_tier_suggestion": violations_raw.get("risk_tier_suggestion"),
        "summary": violations_raw.get("summary", ""),
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

SEVERITY_ICONS = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}


def _write_summary(results: list[dict], total_by_severity: dict[str, int]) -> None:
    if not GITHUB_STEP_SUMMARY:
        return

    lines = [
        "# 🛡️ EU AI Act Compliance Scan",
        "",
        "## Summary",
        f"| Severity | Count |",
        f"|----------|-------|",
        f"| 🔴 CRITICAL | {total_by_severity.get('CRITICAL', 0)} |",
        f"| 🟠 HIGH | {total_by_severity.get('HIGH', 0)} |",
        f"| 🟡 MEDIUM | {total_by_severity.get('MEDIUM', 0)} |",
        f"| 🔵 LOW | {total_by_severity.get('LOW', 0)} |",
        "",
    ]

    for r in results:
        if not r.get("violations"):
            continue
        lines += [
            f"## 📄 `{r['file']}`",
            f"*{r.get('summary', '')}*",
            "",
            "| Rule | Article | Severity | Description |",
            "|------|---------|----------|-------------|",
        ]
        for v in r["violations"]:
            icon = SEVERITY_ICONS.get(v.get("severity", ""), "")
            lines.append(
                f"| {v.get('rule_id', '')} | {v.get('article', '')} "
                f"| {icon} {v.get('severity', '')} | {v.get('description', '')} |"
            )
        lines += [
            "",
            "<details><summary>Recommendations</summary>",
            "",
        ]
        for v in r["violations"]:
            lines.append(f"**{v.get('rule_id')} — {v.get('title')}**: {v.get('recommendation', '')}")
            lines.append("")
        lines += ["</details>", ""]

    if not any(r.get("violations") for r in results):
        lines += ["## ✅ No violations found", ""]

    lines += [
        "---",
        "*Generated by [EU AI Act Compliance Scanner](https://github.com/ajinkyachintawar/eu-ai-act-compliance-agent)*",
    ]

    with open(GITHUB_STEP_SUMMARY, "a") as f:
        f.write("\n".join(lines))


def _set_output(key: str, value: str) -> None:
    if GITHUB_OUTPUT:
        with open(GITHUB_OUTPUT, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"::set-output name={key}::{value}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    files = _discover_files()
    if not files:
        print("⚠️  No Python files found matching pattern:", SCAN_FILES)
        _set_output("total-violations", "0")
        _set_output("critical-count", "0")
        _set_output("high-count", "0")
        return

    print(f"🔍 Scanning {len(files)} file(s) for EU AI Act compliance...")
    client = _client()
    results: list[dict] = []

    for file_path in files:
        print(f"  → {file_path}")
        try:
            result = scan_file(client, file_path)
            results.append(result)
        except Exception as e:
            print(f"  ⚠️  Skipped {file_path}: {e}")

    # Aggregate counts
    all_violations = [v for r in results for v in r.get("violations", [])]
    total_by_severity: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in all_violations:
        sev = v.get("severity", "LOW")
        total_by_severity[sev] = total_by_severity.get(sev, 0) + 1

    total = len(all_violations)

    # Print console summary
    print(f"\n{'='*60}")
    print(f"EU AI Act Compliance Scan Complete — {total} violation(s) found")
    print(f"  🔴 CRITICAL: {total_by_severity['CRITICAL']}")
    print(f"  🟠 HIGH:     {total_by_severity['HIGH']}")
    print(f"  🟡 MEDIUM:   {total_by_severity['MEDIUM']}")
    print(f"  🔵 LOW:      {total_by_severity['LOW']}")
    print(f"{'='*60}\n")

    for r in results:
        if r.get("violations"):
            print(f"📄 {r['file']}: {r.get('summary', '')}")
            for v in r["violations"]:
                icon = SEVERITY_ICONS.get(v.get("severity", ""), "•")
                print(f"  {icon} [{v.get('rule_id')}] {v.get('title')} — {v.get('description', '')}")
                print(f"     Fix: {v.get('recommendation', '')}")

    # Save JSON report
    report_path = "eu-ai-act-scan-report.json"
    with open(report_path, "w") as f:
        json.dump({
            "scanned_files": files,
            "results": results,
            "summary": total_by_severity,
            "total_violations": total,
            "fail_on": FAIL_ON,
        }, f, indent=2)
    print(f"\n📄 Full report saved to: {report_path}")

    # Write GitHub step summary
    _write_summary(results, total_by_severity)

    # Set outputs
    _set_output("total-violations", str(total))
    _set_output("critical-count", str(total_by_severity["CRITICAL"]))
    _set_output("high-count", str(total_by_severity["HIGH"]))
    _set_output("report-path", report_path)

    # Fail if violations at/above threshold
    if FAIL_ON in SEVERITY_ORDER:
        threshold_idx = SEVERITY_ORDER.index(FAIL_ON)
        blocking = sum(
            count for sev, count in total_by_severity.items()
            if sev in SEVERITY_ORDER and SEVERITY_ORDER.index(sev) >= threshold_idx
        )
        if blocking > 0:
            print(f"\n❌ Action failed: {blocking} violation(s) at or above '{FAIL_ON}' severity.")
            sys.exit(1)

    print("\n✅ Scan passed.")


if __name__ == "__main__":
    main()
