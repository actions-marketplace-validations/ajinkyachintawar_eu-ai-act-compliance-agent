from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set. Check your .env file.")
    return value


# --- NIM API keys (two separate keys for the two NIM endpoints) ---
NIM_API_KEY_INFERENCE: str = _require("NIM_API_KEY_INFERENCE")
NIM_API_KEY_EMBED: str = _require("NIM_API_KEY_EMBED")

# --- Shared NIM base URL ---
NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

# --- Groq (fast inference for scanner) ---
GROQ_API_KEY: str = _require("GROQ_API_KEY")
GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
SCANNER_MODEL: str = "llama-3.3-70b-versatile"   # Groq: ~250 tok/s vs NIM ~10 tok/s

# --- Model identifiers ---
MISTRAL_MODEL: str = "mistralai/mistral-large-3-675b-instruct-2512"
EMBEDDING_MODEL: str = "nvidia/nv-embed-v1"

# --- Supabase ---
SUPABASE_URL: str = _require("SUPABASE_URL")
SUPABASE_KEY: str = _require("SUPABASE_KEY")

# --- RAG constants ---
TOP_K_DEFAULT: int = 5
CHUNKS_TABLE: str = "eu_ai_act_chunks"
