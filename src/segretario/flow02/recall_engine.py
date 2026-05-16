from __future__ import annotations

from pathlib import Path


class RecallEngine:
    """L3: recall keyword-based su index.md (stub; §8.2 implementa il semantico)."""

    def __init__(self, index_path: Path) -> None:
        self._index_path = index_path

    def recall(self, query: str, max_tokens: int = 4000) -> str | None:
        if not self._index_path.exists():
            return None
        text = self._index_path.read_text(encoding="utf-8", errors="replace")
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
