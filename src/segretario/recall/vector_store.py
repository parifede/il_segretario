from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class VectorHit:
    """Raw hit returned from vector store query before enrichment."""
    note_path: str
    score: float  # cosine distance: lower is more similar


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, note_path: str, embedding: list[float], content_hash: str) -> None:
        """Insert or update the embedding for a note. Atomic + idempotent."""
        ...

    def delete(self, note_path: str) -> None:
        """Remove note from both indexed_notes and note_vectors tables."""
        ...

    def query(self, embedding: list[float], k: int = 5) -> list[VectorHit]:
        """Return top-k hits by cosine similarity. Lower score = more similar."""
        ...

    def get_indexed_hash(self, note_path: str) -> str | None:
        """Return the stored content_hash for a note, or None if not indexed."""
        ...

    def list_indexed_paths(self) -> set[str]:
        """Return the set of all indexed note paths for diff computation."""
        ...

    def health_check(self) -> bool:
        """Return True if store is operational (connection + vec extension loaded)."""
        ...
