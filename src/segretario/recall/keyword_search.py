from __future__ import annotations
from pathlib import Path


def keyword_search(index_path: Path, query: str, max_tokens: int = 4000) -> str | None:
    """Keyword search over meta/index.md. Legacy fallback, called explicitly by RecallEngine.

    NOT the automatic fallback: invoked only when the caller (Task 3 wizard or explicit
    override) selects keyword mode. Pure function, no side effects.
    """
    if not index_path.exists():
        return None
    text = index_path.read_text(encoding="utf-8", errors="replace")
    keywords = [w.lower() for w in query.split() if len(w) > 3]
    if not keywords:
        return None
    lines = text.splitlines()
    matched = [line for line in lines if any(kw in line.lower() for kw in keywords)]
    if not matched:
        return None
    result = "\n".join(matched)
    char_limit = max_tokens * 4
    return result[:char_limit] if len(result) > char_limit else result
