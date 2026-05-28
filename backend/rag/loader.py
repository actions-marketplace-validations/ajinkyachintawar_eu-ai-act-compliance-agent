from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

# Matches "Article 6", "Article 6a", "ARTICLE 6" anywhere in a stripped line.
# Separator between ID and title can be a dash, en/em-dash, colon, or just space.
_ARTICLE_RE = re.compile(
    r"(Article\s+\d+[a-z]?)\s*[–\-—:]?\s*(.*)",
    re.IGNORECASE,
)
# Matches "Annex III", "ANNEX IV" etc. with same flexible separator.
_ANNEX_RE = re.compile(
    r"(Annex\s+[IVXLCDM]+)\s*[–\-—:]?\s*(.*)",
    re.IGNORECASE,
)

_TAG_RULES: dict[str, list[str]] = {
    "prohibited": ["prohibited", "unacceptable risk", "article 5"],
    "high-risk": ["high-risk", "high risk", "annex iii", "article 6", "article 7"],
    "transparency": ["transparency", "article 13", "article 50", "disclosure", "chatbot", "deepfake"],
    "human-oversight": ["human oversight", "article 14"],
    "data-governance": ["data governance", "article 10", "training data"],
    "risk-management": ["risk management", "article 9"],
    "technical-documentation": ["technical documentation", "annex iv", "article 11", "article 12", "logging", "record-keeping"],
    "accuracy-robustness": ["accuracy", "robustness", "cybersecurity", "article 15"],
    "obligations-providers": ["obligations of providers", "article 16", "article 17", "article 18", "article 19", "article 20", "article 21"],
    "obligations-deployers": ["obligations of deployers", "deployer", "article 26", "article 29", "fundamental rights impact"],
    "conformity": ["conformity assessment", "article 43", "article 44"],
    "general-purpose": ["general purpose", "gpai", "article 51", "article 52", "article 53", "article 54", "article 55"],
}


def _infer_tags(text: str) -> list[str]:
    lower = text.lower()
    return [tag for tag, keywords in _TAG_RULES.items() if any(kw in lower for kw in keywords)]


def _extract_annex_label(article_id: str) -> str | None:
    m = _ANNEX_RE.match(article_id)
    if not m:
        return None
    parts = m.group(1).split()
    return parts[-1].upper() if len(parts) > 1 else None


def _match_header(line: str) -> re.Match | None:
    """Return the first Article or Annex header match found in line, or None."""
    stripped = line.strip()
    # Try article first, then annex. Use search so the pattern can appear
    # after leading numbering like "6. Article 6 –" in some PDF layouts.
    return _ARTICLE_RE.search(stripped) or _ANNEX_RE.search(stripped)


def _lines_to_chunks(lines: list[str], source_file: str) -> list[dict]:
    chunks: list[dict] = []
    current_id = "Preamble"
    current_title = "Preamble / Recitals"
    current_lines: list[str] = []

    def _flush() -> None:
        text = "\n".join(current_lines).strip()
        if not text:
            return
        annex = _extract_annex_label(current_id)
        tags = _infer_tags(f"{current_id} {current_title} {text}")
        chunks.append(
            {
                "article_id": current_id,
                "title": current_title,
                "tags": tags,
                "annex": annex,
                "text": text,
                "source_file": source_file,
            }
        )

    for line in lines:
        m = _match_header(line)
        if m:
            _flush()
            current_id = m.group(1).strip()
            # group(2) is everything after the separator; may be empty for
            # single-line headings like "Article 6\n<title on next line>"
            raw_title = m.group(2).strip()
            current_title = raw_title if raw_title else current_id
            current_lines = []
        else:
            current_lines.append(line)

    _flush()
    return chunks


def _load_pdf(path: Path) -> list[dict]:
    reader = PdfReader(str(path))
    lines: list[str] = []
    for page in reader.pages:
        lines.extend((page.extract_text() or "").splitlines())
    return _lines_to_chunks(lines, source_file=path.name)


def _load_html(path: Path) -> list[dict]:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    lines = [
        tag.get_text(separator=" ", strip=True)
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"])
        if tag.get_text(strip=True)
    ]
    return _lines_to_chunks(lines, source_file=path.name)


def load_corpus(folder_path: str) -> list[dict]:
    """Load all PDF and HTML files from a folder and return article-level chunks."""
    folder = Path(folder_path)
    all_chunks: list[dict] = []

    for path in sorted(folder.iterdir()):
        if path.suffix.lower() == ".pdf":
            chunks = _load_pdf(path)
        elif path.suffix.lower() in {".html", ".htm"}:
            chunks = _load_html(path)
        else:
            continue

        print(f"  Loaded {len(chunks):4d} chunks from '{path.name}'")
        all_chunks.extend(chunks)

    print(f"\nTotal chunks across corpus: {len(all_chunks)}")
    if all_chunks:
        s = all_chunks[0]
        print(
            f"Sample chunk — article_id: '{s['article_id']}' | "
            f"title: '{s['title']}' | "
            f"tags: {s['tags']} | "
            f"text preview: '{s['text'][:120].replace(chr(10), ' ')}...'"
        )

    return all_chunks


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "backend/rag/corpus"
    load_corpus(path)
