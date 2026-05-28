from __future__ import annotations

import time
import uuid
from collections import defaultdict

from openai import OpenAI
from supabase import Client, create_client

from backend.config import (
    CHUNKS_TABLE,
    EMBEDDING_MODEL,
    NIM_API_KEY_EMBED,
    NIM_BASE_URL,
    SUPABASE_KEY,
    SUPABASE_URL,
)

_BATCH_SIZE = 50
_RETRY_DELAY = 3
MAX_CHARS = 9_500  # nv-embed-v1 WordPiece tokenises legal text at ~2.6 chars/token;
                   # 9_500 chars ≈ 3_650 tokens — safe headroom under the 4_096 limit


def _embed_client() -> OpenAI:
    return OpenAI(api_key=NIM_API_KEY_EMBED, base_url=NIM_BASE_URL)


def _supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def _split_chunk(chunk: dict) -> list[dict]:
    """Split a chunk whose embedded text exceeds MAX_CHARS into sub-chunks.

    Each sub-chunk inherits all metadata from the parent and gets an
    article_id suffix: "Article 6" → "Article 6.1", "Article 6.2", ...
    """
    prefix = f"passage: {chunk['article_id']}: {chunk['title']}\n\n"
    text = chunk["text"]

    if len(prefix + text) <= MAX_CHARS:
        return [chunk]

    # How many chars of the body text fit per sub-chunk
    body_budget = MAX_CHARS - len(prefix)
    parts = [text[i : i + body_budget] for i in range(0, len(text), body_budget)]

    return [
        {
            **chunk,
            "article_id": f"{chunk['article_id']}.{i + 1}",
            "text": part,
        }
        for i, part in enumerate(parts)
    ]


def _expand_chunks(chunks: list[dict]) -> list[dict]:
    """Return a new list with oversized or duplicate-keyed chunks uniquely numbered.

    Two sources of (article_id, source_file) collisions:
      1. A single chunk is too large and is split into multiple sub-chunks.
      2. The same heading appears more than once in a document (e.g. ToC + body).
    Both cases get a global sequential suffix so every row in the expanded list
    has a unique (article_id, source_file) pair.
    """
    # First pass: count how many input chunks share each (article_id, source_file) key.
    occurrence_count: dict[tuple, int] = defaultdict(int)
    for c in chunks:
        occurrence_count[(c["article_id"], c["source_file"])] += 1

    expanded: list[dict] = []
    sub_counters: dict[tuple, int] = defaultdict(int)

    for chunk in chunks:
        key = (chunk["article_id"], chunk["source_file"])
        sub = _split_chunk(chunk)
        needs_suffix = len(sub) > 1 or occurrence_count[key] > 1

        if len(sub) > 1:
            print(
                f"  Split '{chunk['article_id']}' ({len(chunk['text'])} chars) "
                f"→ {len(sub)} sub-chunks"
            )

        for s in sub:
            if needs_suffix:
                sub_counters[key] += 1
                expanded.append({**s, "article_id": f"{chunk['article_id']}.{sub_counters[key]}"})
            else:
                expanded.append(s)

    return expanded


def embed_and_upsert(chunks: list[dict]) -> None:
    if not chunks:
        print("No chunks provided — skipping embed_and_upsert.")
        return

    expanded = _expand_chunks(chunks)
    if len(expanded) != len(chunks):
        print(f"After splitting: {len(chunks)} chunks → {len(expanded)} sub-chunks\n")

    embed = _embed_client()
    supabase = _supabase_client()
    total_upserted = 0
    failed: list[str] = []

    for batch_start in range(0, len(expanded), _BATCH_SIZE):
        batch = expanded[batch_start : batch_start + _BATCH_SIZE]
        texts = [f"passage: {c['article_id']}: {c['title']}\n\n{c['text']}" for c in batch]
        batch_num = batch_start // _BATCH_SIZE + 1

        embeddings: list[list[float]] = []
        batch_ok = True

        for attempt in range(2):
            try:
                embeddings = _embed_batch(embed, texts)
                break
            except Exception as exc:
                if attempt == 0:
                    print(f"Batch {batch_num} failed ({exc}), retrying in {_RETRY_DELAY}s...")
                    time.sleep(_RETRY_DELAY)
                else:
                    # Batch-level retry exhausted — fall back to one-by-one
                    print(f"Batch {batch_num} failed again. Falling back to per-chunk embedding...")
                    embeddings = []
                    for chunk in batch:
                        text = f"passage: {chunk['article_id']}: {chunk['title']}\n\n{chunk['text']}"
                        try:
                            emb = _embed_batch(embed, [text])[0]
                            embeddings.append(emb)
                        except Exception as chunk_exc:
                            print(f"  SKIP '{chunk['article_id']}' — {chunk_exc}")
                            failed.append(chunk["article_id"])
                            embeddings.append(None)  # placeholder, filtered out below
                    batch_ok = False

        pairs = list(zip(batch, embeddings))
        rows = [
            {
                "id": str(uuid.uuid4()),
                "article_id": c["article_id"],
                "title": c["title"],
                "tags": c["tags"],
                "annex": c["annex"],
                "text": c["text"],
                "embedding": emb,
                "source_file": c["source_file"],
            }
            for c, emb in pairs
            if emb is not None
        ]

        if rows:
            supabase.table(CHUNKS_TABLE).upsert(rows, on_conflict="article_id,source_file").execute()
            total_upserted += len(rows)

        status = "ok" if batch_ok else f"{len(rows)}/{len(batch)} succeeded"
        print(f"Batch {batch_num}: upserted {len(rows)} rows [{status}] (running total: {total_upserted})")

    print(f"\nDone. Total rows upserted to '{CHUNKS_TABLE}': {total_upserted}")
    if failed:
        print(f"Skipped {len(failed)} chunk(s) due to embedding errors:")
        for article_id in failed:
            print(f"  - {article_id}")


if __name__ == "__main__":
    import sys
    from backend.rag.loader import load_corpus

    folder = sys.argv[1] if len(sys.argv) > 1 else "backend/rag/corpus"
    chunks = load_corpus(folder)
    embed_and_upsert(chunks)
