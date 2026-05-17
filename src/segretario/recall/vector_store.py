from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class VectorHit:
    """Raw hit returned from vector store query before enrichment."""
    note_path: str
    chunk_index: int
    section_title: str | None
    score: float  # cosine similarity: higher is more similar, range [-1, 1]; practical [0, 1] for normalized embeddings


@runtime_checkable
class VectorStore(Protocol):
    def upsert_chunk(
        self,
        note_path: str,
        chunk_index: int,
        section_title: str | None,
        embedding: list[float],
        content_hash: str,
        note_hash: str,
    ) -> None:
        """Insert or update the embedding for a chunk. Atomic + idempotent."""
        ...

    def delete_note(self, note_path: str) -> None:
        """Remove all chunks for a note from both indexed_chunks and chunk_vectors."""
        ...

    def query(self, embedding: list[float], k: int = 5) -> list[VectorHit]:
        """Return top-k hits ordered by descending similarity (highest first)."""
        ...

    def get_indexed_note_hash(self, note_path: str) -> str | None:
        """Return the stored note_hash for a note, or None if not indexed."""
        ...

    def list_indexed_paths(self) -> set[str]:
        """Return the set of all indexed note paths for diff computation."""
        ...

    def health_check(self) -> bool:
        """Return True if store is operational (connection + vec extension loaded)."""
        ...
