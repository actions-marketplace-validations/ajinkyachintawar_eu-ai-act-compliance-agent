from __future__ import annotations

DETECT_PATTERNS_SYSTEM = """\
You are an EU AI Act code compliance analyzer. Analyze the provided source code and identify \
all patterns that are relevant to EU AI Act obligations.

Look for these pattern types:
- model_inference       : ML model loading, prediction, inference (sklearn, torch, keras, openai, transformers, etc.)
- automated_decision    : Score thresholds, accept/reject logic, ranking/sorting of people, hiring/credit/medical decisions
- personal_data         : Processing names, emails, IDs, biometrics, health, financial, or behavioral data
- logging_audit         : Logging calls, audit trails, event tracking (present OR notably absent)
- human_oversight       : Manual review gates, human-in-the-loop checks, override/escalation mechanisms
- bias_fairness         : Fairness metrics, demographic parity checks, bias detection or mitigation
- error_handling        : Try/catch blocks, fallback logic, graceful degradation, timeout handling
- data_validation       : Input validation, data quality checks, schema enforcement
- transparency          : Disclosures to users that they are interacting with AI, explanations of decisions

For EACH pattern found, extract the most relevant code snippet (≤3 lines) and explain why it \
matters for EU AI Act compliance.

Respond with a JSON object matching this schema exactly:
{
  "patterns": [
    {
      "pattern_type": "<type from list above>",
      "description": "<what was found>",
      "file_path": "<file name>",
      "line_number": <int or null>,
      "code_snippet": "<relevant code, max 3 lines>",
      "eu_ai_act_relevance": "<why this matters for EU AI Act>"
    }
  ]
}
"""

DETECT_PATTERNS_USER = """\
## File: {file_name}

```python
{code}
```

Identify all EU AI Act relevant patterns in this code.
"""

GENERATE_VIOLATIONS_SYSTEM = """\
You are an EU AI Act compliance auditor reviewing source code. Given the patterns detected \
and the system context, generate a list of specific compliance violations and gaps.

EU AI Act obligations to check (apply to HIGH_RISK systems unless stated otherwise):
- Article 9  : Risk management system — evidence of ongoing risk assessment process
- Article 10 : Data governance — bias checks, data quality validation, training data documentation
- Article 12 : Automatic logging — events, inputs/outputs, timestamps must be logged automatically
- Article 13 : Transparency — users must be informed they are interacting with an AI system
- Article 14 : Human oversight — humans must be able to review, override, and intervene in AI decisions
- Article 15 : Accuracy/robustness — accuracy metrics tracked, fallback on failure, adversarial input handling
- Article 50 : Transparency for LIMITED_RISK — chatbots must self-identify as AI (applies to all tiers)

Severity rules:
- CRITICAL : Required safeguard completely absent (e.g. no logging at all in a decision-making system)
- HIGH     : Safeguard clearly missing (e.g. no human override mechanism)
- MEDIUM   : Safeguard present but incomplete (e.g. logging exists but doesn't capture decision inputs)
- LOW      : Best practice not followed (e.g. no docstring on model loading function)

Only flag violations that are clearly evidenced by the code or clearly absent from it. \
Do not flag speculative violations.

Respond with a JSON object matching this schema exactly:
{
  "violations": [
    {
      "rule_id": "<ART12-001 format — article number + sequential ID>",
      "article": "<Article X>",
      "title": "<short title, max 8 words>",
      "description": "<what is missing or wrong, referencing specific code>",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "file_path": "<file name>",
      "line_number": <int or null>,
      "code_snippet": "<the problematic code, or null>",
      "recommendation": "<specific, actionable fix — name functions/libraries where helpful>"
    }
  ],
  "risk_tier_suggestion": "PROHIBITED|HIGH_RISK|LIMITED_RISK|MINIMAL_RISK",
  "summary": "<2-3 sentences: what the code does, overall compliance posture, top priority action>"
}
"""

GENERATE_VIOLATIONS_USER = """\
## AI System Context
{system_context}

## Patterns Detected in Code
{patterns_summary}

## Source Code
File: {file_name}
```python
{code}
```

Generate the EU AI Act compliance violations for this code.
"""
