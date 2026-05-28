# EU AI Act Compliance Classifier Agent

FastAPI + LangGraph agent that classifies AI systems against the EU AI Act
and generates structured compliance reports (risk tier, obligations, gap
analysis, Annex IV draft).

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + LangGraph |
| Inference | Mistral Large (`mistralai/mistral-large-3-675b-instruct-2512`) via NVIDIA NIM |
| Embeddings | `nvidia/nv-embed-v1` via NVIDIA NIM |
| SDK | OpenAI Python SDK (OpenAI-compatible NIM API) |
| Vector DB | Supabase pgvector (EU region) |
| Frontend | React + Tailwind (Day 3) |
| Deploy | Render EU + Vercel |

---

## Local setup

```bash
cd eu-ai-act-agent
python -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env   # fill in NIM keys + Supabase credentials
uvicorn backend.main:app --reload
```

API docs: http://localhost:8000/docs

Health check: `GET /health` → `{"status": "ok", "model": "mistralai/mistral-large-3-675b-instruct-2512"}`

---

## Supabase: one-time setup

Run these SQL statements in the Supabase SQL editor **once** before ingesting
any documents.

### 1. Enable pgvector

```sql
create extension if not exists vector;
```

### 2. Create the chunks table

`nvidia/nv-embed-v1` produces **4096-dimensional** vectors.

```sql
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
```

### 3. Create the vector similarity search function

```sql
create or replace function match_eu_ai_act_chunks(
  query_embedding  vector(4096),
  match_count      int     default 5,
  filter_annex     text    default null,
  filter_tag       text    default null
)
returns table (
  id             uuid,
  article_id     text,
  title          text,
  tags           text[],
  annex          text,
  text           text,
  source_file    text,
  similarity     float
)
language sql stable
as $$
  select
    id,
    article_id,
    title,
    tags,
    annex,
    text,
    source_file,
    1 - (embedding <=> query_embedding) as similarity
  from eu_ai_act_chunks
  where
    (filter_annex is null or annex = filter_annex)
    and (filter_tag is null or filter_tag = any(tags))
  order by embedding <=> query_embedding
  limit match_count;
$$;
```

### 4. Create the HNSW index

```sql
create index if not exists eu_ai_act_chunks_embedding_idx
  on eu_ai_act_chunks
  using hnsw (embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);
```

---

## Corpus ingestion

See `backend/rag/corpus/README.md` for the 8 documents to download.

After downloading:

```bash
python -m backend.rag.embedder backend/rag/corpus
```

Expected output: ~800–1200 chunks, 50 rows per batch.

---

## Environment variables

| Variable | Purpose |
|---|---|
| `NIM_API_KEY_INFERENCE` | NVIDIA NIM key for Mistral Large inference |
| `NIM_API_KEY_EMBED` | NVIDIA NIM key for nv-embed-v1 embeddings |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon or service-role key |

---

## Project structure

```
eu-ai-act-agent/
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Env vars + constants
│   ├── agents/              # LangGraph agent nodes (Day 2)
│   ├── rag/
│   │   ├── loader.py        # PDF/HTML → article-level chunks
│   │   ├── embedder.py      # Chunks → NIM embeddings → Supabase
│   │   ├── retriever.py     # Query → top-k chunks
│   │   └── corpus/          # Downloaded documents (gitignored)
│   ├── models/
│   │   └── schemas.py       # All Pydantic v2 models
│   └── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```
