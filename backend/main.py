from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import MISTRAL_MODEL
from backend.models.schemas import ComplianceReport, ScanReport, ScanRequest, SystemDescription

app = FastAPI(
    title="EU AI Act Compliance Classifier",
    description="Classifies AI systems against the EU AI Act and generates structured compliance reports.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "model": MISTRAL_MODEL}


class DescribeRequest(BaseModel):
    description: str


@app.post("/describe", response_model=ComplianceReport)
def describe(request: DescribeRequest) -> ComplianceReport:
    """Accept a plain-English description, extract structured fields, then run the compliance graph."""
    from backend.agents.nodes import extract_fields_from_text

    try:
        system = extract_fields_from_text(request.description)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Field extraction failed: {exc}") from exc

    return _run_graph(system)


def _run_graph(system: SystemDescription) -> ComplianceReport:
    from backend.agents.graph import compiled_graph

    initial_state = {
        "system": system,
        "context_chunks": [],
        "classification": None,
        "article6_exception": None,
        "obligations": None,
        "annex_iv_draft": None,
        "report": None,
    }

    try:
        final_state = compiled_graph.invoke(initial_state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    report: ComplianceReport | None = final_state.get("report")
    if report is None:
        raise HTTPException(status_code=500, detail="Agent graph did not produce a report.")

    return report


@app.post("/analyse", response_model=ComplianceReport)
def analyse(system: SystemDescription) -> ComplianceReport:
    return _run_graph(system)


@app.post("/export/annex-iv")
def export_annex_iv(report: ComplianceReport) -> StreamingResponse:
    """Generate and download an Annex IV Technical Documentation .docx from a ComplianceReport."""
    from backend.export.annex_iv import build_annex_iv_docx

    try:
        docx_bytes = build_annex_iv_docx(report)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    safe_name = report.system.name.replace(" ", "_")[:40]
    filename = f"Annex_IV_{safe_name}.docx"

    return StreamingResponse(
        iter([docx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/scan", response_model=ScanReport)
def scan(request: ScanRequest) -> ScanReport:
    """Scan source code for EU AI Act compliance violations."""
    from backend.agents.scanner_graph import compiled_scanner

    initial_state = {
        "file_name": request.file_name,
        "code": request.code,
        "system_context": request.system_context or "",
        "patterns": [],
        "violations": [],
        "risk_tier_suggestion": None,
        "summary": "",
        "report": None,
    }

    try:
        final_state = compiled_scanner.invoke(initial_state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    report: ScanReport | None = final_state.get("report")
    if report is None:
        raise HTTPException(status_code=500, detail="Scanner graph did not produce a report.")

    return report
