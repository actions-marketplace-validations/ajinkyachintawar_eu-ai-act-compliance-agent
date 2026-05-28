# EU AI Act Compliance Classifier Agent

> A multi-agent LangGraph system that classifies AI systems against the EU AI Act (Regulation 2024/1689), generates structured compliance reports, scans source code for regulatory violations, and ships as a reusable GitHub Action CI/CD gate.

---

## What it does

Paste a plain-English description of your AI system and get back:

- **Risk tier** — Prohibited / High-Risk / Limited-Risk / Minimal-Risk with confidence score
- **Article 6 exception check** — determines if a High-Risk system qualifies for the safety-component carve-out
- **Obligations checklist** — every applicable EU AI Act article (Art. 9–15, Art. 50), each marked MET / NOT_MET / UNCLEAR
- **Annex IV draft** — download a `.docx` technical documentation template pre-filled from your description
- **Code scanner** — paste Python source code to get per-line violation findings with article citations and fix recommendations
- **MCP server** — connect Claude Desktop directly to the compliance pipeline
- **GitHub Action** — drop a YAML block into any repo to gate PRs on EU AI Act compliance

---

## Architecture

### Compliance graph (LangGraph)

```
User description (free text)
        │
        ▼
 extract_fields          ← LLM: plain text → structured SystemDescription
        │
        ▼
    retrieve             ← RAG: nv-embed-v1 (NIM) → Supabase pgvector top-8 chunks
        │
        ▼
    classify             ← LLM: tier + confidence + Annex III category
        │
   ┌────┴────────────────┐
   │ HIGH_RISK?          │ other tiers
   ▼                     ▼
check_article6      check_obligations
   │                     │
   └──────────┬──────────┘
              ▼
       check_obligations   ← LLM: per-article MET/NOT_MET/UNCLEAR
              │
        ┌─────┴──────────────────┐
        │ HIGH_RISK + no exception│ other
        ▼                        ▼
   draft_annex_iv           assemble
        │                        │
        └───────────┬────────────┘
                    ▼
               assemble          ← builds ComplianceReport
```

### Code scanner graph (LangGraph)

```
Source code
     │
     ▼
detect_patterns          ← LLM: find EU AI Act relevant code patterns
     │
     ▼
generate_violations      ← LLM: map patterns → article violations with severity
     │
     ▼
assemble_scan_report     ← builds ScanReport
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI |
| Agent orchestration | LangGraph (`StateGraph` with conditional routing) |
| LLM inference | `llama-3.3-70b-versatile` via **Groq** (~1s/call) |
| Embeddings | `nvidia/nv-embed-v1` via **NVIDIA NIM** (4096-dim) |
| Vector DB | Supabase pgvector · 177 chunks · HNSW index |
| MCP server | fastmcp 3.3.1 (job-queue pattern) |
| Document export | python-docx |
| CI/CD gate | GitHub composite Action |
| Demo | Single-page HTML · Tailwind CDN · vanilla JS |

> **Inference split:** Groq handles all LLM calls (compliance graph + scanner). NVIDIA NIM is used **only** for query embeddings during RAG retrieval — there is no Groq-equivalent embedding model at the required 4096 dimensions.

---

## Features

| # | Feature | Entry point |
|---|---|---|
| 1 | Free-text input → structured fields → compliance report | `POST /describe` |
| 2 | Claude Desktop MCP integration (job-queue pattern) | `backend/mcp_server.py` |
| 3 | Code scanner — pattern detection + violation generation | `POST /scan` |
| 4 | Scanner LangGraph subgraph (3-node sequential) | `backend/agents/scanner_graph.py` |
| 5 | GitHub Action CI/CD gate (zero-dependency, Groq-only) | `action.yml` + `scan_action.py` |
| 6 | Annex IV `.docx` export (colour-coded, print-ready) | `POST /export/annex-iv` |
| 7 | Single-page interactive demo (no build step) | `demo/index.html` |

---

## Quick start

### Prerequisites

- Python 3.11+
- A [Groq](https://console.groq.com) API key (free tier works)
- A [NVIDIA NIM](https://build.nvidia.com) API key for embeddings
- A [Supabase](https://supabase.com) project with pgvector enabled

### 1 — Clone and install

```bash
git clone https://github.com/ajinkyachintawar/eu-ai-act-compliance-agent.git
cd eu-ai-act-compliance-agent
python -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
```

### 2 — Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your keys (see Environment variables below)
```

### 3 — Set up Supabase (one-time)

Run the SQL in the [Supabase setup](#supabase-setup) section below, then ingest the EU AI Act corpus:

```bash
python -m backend.rag.embedder backend/rag/corpus
# Expected: ~177 chunks uploaded
```

### 4 — Start the API

```bash
uvicorn backend.main:app --reload --port 8001
```

API docs available at [http://localhost:8001/docs](http://localhost:8001/docs)

### 5 — Open the demo

Open `demo/index.html` directly in your browser — no build step needed.

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | ✅ | Groq inference for all LLM calls |
| `NIM_API_KEY_EMBED` | ✅ | NVIDIA NIM `nv-embed-v1` embeddings |
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_KEY` | ✅ | Supabase anon or service-role key |

Copy `.env.example` to `.env` and fill these in. Never commit `.env`.

---

## API endpoints

### `GET /health`
```json
{ "status": "ok", "model": "llama-3.3-70b-versatile" }
```

### `POST /describe` — plain text → compliance report
```bash
curl -X POST http://localhost:8001/describe \
  -H "Content-Type: application/json" \
  -d '{"description": "A CV screening tool that automatically ranks job applicants using ML."}'
```

Returns a full `ComplianceReport` with risk tier, confidence, obligations checklist, Article 6 exception analysis, and Annex IV draft.

### `POST /analyse` — structured input → compliance report
```bash
curl -X POST http://localhost:8001/analyse \
  -H "Content-Type: application/json" \
  -d '{
    "name": "CV Screener",
    "use_case": "Rank job applicants automatically",
    "sector": "EMPLOYMENT",
    "inputs": "CVs, cover letters",
    "outputs": "Ranked shortlist",
    "affected_persons": "Job applicants",
    "decision_type": "AUTONOMOUS"
  }'
```

### `POST /scan` — source code → violation report
```bash
curl -X POST http://localhost:8001/scan \
  -H "Content-Type: application/json" \
  -d '{
    "code": "import openai\ndef rank_applicants(cvs): ...",
    "file_name": "screener.py",
    "system_context": "CV screening tool for recruitment"
  }'
```

Returns a `ScanReport` with patterns found, violations by article, severity (CRITICAL / HIGH / MEDIUM / LOW), and per-violation fix recommendations.

### `POST /export/annex-iv` — download Annex IV `.docx`
```bash
curl -X POST http://localhost:8001/export/annex-iv \
  -H "Content-Type: application/json" \
  -d '{...ComplianceReport JSON...}' \
  --output annex_iv.docx
```

---

## GitHub Action — CI/CD compliance gate

Add this to any repository to scan Python files on every PR:

```yaml
# .github/workflows/eu-ai-act-scan.yml
name: EU AI Act Compliance Scan

on:
  pull_request:
    paths: ["**/*.py"]
  push:
    branches: [main]
    paths: ["**/*.py"]
  workflow_dispatch:

jobs:
  compliance-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: EU AI Act Compliance Scan
        uses: ajinkyachintawar/eu-ai-act-compliance-agent@main
        with:
          groq-api-key: ${{ secrets.GROQ_API_KEY }}
          files: "src/main.py src/model.py"
          system-context: "Brief description of what your AI system does"
          fail-on: HIGH   # NONE | LOW | MEDIUM | HIGH | CRITICAL

      - name: Upload scan report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: eu-ai-act-scan-report
          path: eu-ai-act-scan-report.json
          retention-days: 30
```

### Action inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `groq-api-key` | ✅ | — | Groq API key (store as repo secret) |
| `files` | ✅ | — | Space-separated file paths or glob patterns |
| `system-context` | ❌ | `""` | Short description of your AI system (improves accuracy) |
| `fail-on` | ❌ | `HIGH` | Minimum severity that fails the workflow |

### Action outputs

| Output | Description |
|---|---|
| `total-violations` | Total number of violations found |
| `critical-count` | Number of CRITICAL violations |
| `high-count` | Number of HIGH violations |
| `report-path` | Path to the JSON scan report |

Only the `openai` package is required — the Action installs it automatically. No backend server needed.

---

## MCP server (Claude Desktop)

The MCP server uses a **job-queue pattern** to work around Claude Desktop's 60-second timeout. Long-running pipelines (~30s) run in background threads; tools return instantly.

### Start the server
```bash
python -m backend.mcp_server
```

### Add to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "eu-ai-act": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "/absolute/path/to/eu-ai-act-compliance-agent"
    }
  }
}
```

### Available tools

**`start_analysis`** — starts the pipeline, returns a `job_id` immediately
- `description` (str): plain-text AI system description
- `mode` (str): `"full_report"` (default) or `"quick_classify"`

**`get_result`** — poll with the `job_id` to retrieve the finished report

---

## Supabase setup

Run these SQL statements once in the Supabase SQL editor.

```sql
-- 1. Enable pgvector
create extension if not exists vector;

-- 2. Chunks table (nv-embed-v1 produces 4096-dim vectors)
create table if not exists eu_ai_act_chunks (
  id           uuid primary key default gen_random_uuid(),
  article_id   text         not null,
  title        text         not null,
  tags         text[]       not null default '{}',
  annex        text,
  text         text         not null,
  embedding    vector(4096) not null,
  source_file  text         not null,
  created_at   timestamptz  not null default now(),
  unique (article_id, source_file)
);

-- 3. Similarity search function
create or replace function match_chunks(
  query_embedding  vector(4096),
  match_count      int default 5
)
returns table (
  id          uuid,
  article_id  text,
  title       text,
  tags        text[],
  annex       text,
  text        text,
  source_file text,
  similarity  float
)
language sql stable as $$
  select id, article_id, title, tags, annex, text, source_file,
         1 - (embedding <=> query_embedding) as similarity
  from eu_ai_act_chunks
  order by embedding <=> query_embedding
  limit match_count;
$$;

-- 4. HNSW index for fast ANN search
create index if not exists eu_ai_act_chunks_embedding_idx
  on eu_ai_act_chunks
  using hnsw (embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);
```

---

## Project structure

```
eu-ai-act-compliance-agent/
├── backend/
│   ├── main.py                  # FastAPI app — 5 endpoints
│   ├── config.py                # Env vars + model constants
│   ├── mcp_server.py            # fastmcp MCP server (job-queue pattern)
│   ├── agents/
│   │   ├── graph.py             # Compliance LangGraph (6 nodes, conditional routing)
│   │   ├── nodes.py             # Compliance graph node functions
│   │   ├── state.py             # AgentState TypedDict
│   │   ├── prompts.py           # All compliance graph prompts
│   │   ├── scanner_graph.py     # Scanner LangGraph (3-node sequential)
│   │   ├── scanner_nodes.py     # Scanner node functions
│   │   ├── scanner_state.py     # ScannerState TypedDict
│   │   └── scanner_prompts.py   # Scanner prompts
│   ├── export/
│   │   └── annex_iv.py          # python-docx Annex IV builder
│   ├── rag/
│   │   ├── loader.py            # PDF/HTML → article-level chunks
│   │   ├── embedder.py          # Chunks → NIM embeddings → Supabase
│   │   ├── retriever.py         # Query → top-k chunks (NIM embed + pgvector)
│   │   └── corpus/              # Downloaded EU AI Act PDFs (gitignored)
│   ├── models/
│   │   └── schemas.py           # All Pydantic v2 models
│   └── requirements.txt
├── demo/
│   └── index.html               # Single-page demo (Tailwind + vanilla JS)
├── action.yml                   # GitHub composite Action definition
├── scan_action.py               # Standalone scanner (only needs openai)
├── .github/
│   └── workflows/
│       └── eu-ai-act-scan.yml   # Example workflow using the Action
├── .env.example
└── README.md
```

---

## EU AI Act articles covered

| Article | Topic |
|---|---|
| Art. 5 | Prohibited AI practices |
| Art. 6 + Annex III | High-risk classification criteria |
| Art. 9 | Risk management system |
| Art. 10 | Data governance |
| Art. 11 + Annex IV | Technical documentation |
| Art. 12 | Record-keeping and logging |
| Art. 13 | Transparency and information to users |
| Art. 14 | Human oversight |
| Art. 15 | Accuracy, robustness, cybersecurity |
| Art. 50 | Transparency obligations (GPAI / limited-risk) |

---

## License

MIT
