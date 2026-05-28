from __future__ import annotations

from openai import OpenAI
from supabase import Client, create_client

from backend.config import (
    EMBEDDING_MODEL,
    NIM_API_KEY_EMBED,
    NIM_BASE_URL,
    SUPABASE_KEY,
    SUPABASE_URL,
    TOP_K_DEFAULT,
)


def _embed_client() -> OpenAI:
    return OpenAI(api_key=NIM_API_KEY_EMBED, base_url=NIM_BASE_URL)


def _supabase_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _embed_query(client: OpenAI, query: str) -> list[float]:
    # nv-embed-v1 requires the "query: " prefix for retrieval queries
    prefixed = f"query: {query}"
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=[prefixed])
    return response.data[0].embedding


def retrieve(
    query: str,
    k: int = TOP_K_DEFAULT,
) -> list[dict]:
    """Return the top-k most relevant EU AI Act chunks for a query.

    Args:
        query: Natural-language question or system description fragment.
        k: Number of results to return.

    Returns:
        List of dicts with keys: article_id, title, text, similarity.
    """
    embed = _embed_client()
    supabase = _supabase_client()

    embedding = _embed_query(embed, query)

    result = supabase.rpc(
        "match_chunks",
        {"query_embedding": embedding, "match_count": k},
    ).execute()

    return [
        {
            "article_id": row.get("article_id", ""),
            "title": row.get("title", ""),
            "text": row.get("text", ""),
            "similarity": float(row.get("similarity", 0.0)),
        }
        for row in (result.data or [])
    ]


def format_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a prompt-ready context block."""
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(
            f"[{i}] {c['article_id']} — {c['title']}\n"
            f"(similarity: {c['similarity']:.3f})\n"
            f"{c['text'].strip()}"
        )
    return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What are the obligations for high-risk AI systems?"
    print(f"Query: {query}\n")
    results = retrieve(query)
    for r in results:
        print(f"  {r['article_id']!r:30s}  score={r['similarity']:.4f}  {r['title']}")
