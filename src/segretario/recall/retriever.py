from __future__ import annotations
from typing import Protocol
from segretario.recall.models import RecallHit


class Retriever(Protocol):
    """Abstract retriever interface. Allows EmbeddingRetriever + future FTS5 retriever."""

    def search(self, query: str, k: int = 5) -> list[RecallHit]:
        """Search for notes matching the query. Returns ranked hits."""
        ...
