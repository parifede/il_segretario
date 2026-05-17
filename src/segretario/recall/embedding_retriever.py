from __future__ import annotations
import logging
from pathlib import Path

from segretario.recall.chunker import H2OverlapChunker
from segretario.recall.embedder import OllamaEmbedder, EmbedderError
from segretario.recall.models import RecallHit
from segretario.recall.vector_store import VectorStore, VectorHit

logger = logging.getLogger(__name__)


class EmbeddingRetriever:
    """Semantic retriever using embeddings + sqlite-vec.

    Implements the Retriever protocol (structurally, not via explicit inheritance).
    """

    def __init__(
        self, vault_path: Path, store: VectorStore, embedder: OllamaEmbedder
    ) -> None:
        self._vault_path = vault_path
        self._store = store
        self._embedder = embedder
        self._chunker = H2OverlapChunker()

    def search(self, query: str, k: int = 5) -> list[RecallHit]:
        """Search for notes matching the query semantically.

        Returns up to k hits. Skips hits pointing to deleted files or with
        chunk index drift (with WARNING).
        Raises EmbedderError if query embedding fails.
        """
        query_embedding = self._embedder.embed(query)
        vec_hits = self._store.query(query_embedding, k=k)

        results: list[RecallHit] = []
        for hit in vec_hits:
            recall_hit = self._enrich(hit)
            if recall_hit is not None:
                results.append(recall_hit)
        return results

    def _enrich(self, vec_hit: VectorHit) -> RecallHit | None:
        """Enrich a VectorHit by re-chunking the note and extracting the right chunk.

        Returns None if the file is missing or the chunk index is out of range (drift).
        """
        note_path = self._vault_path / vec_hit.note_path
        if not note_path.exists():
            logger.warning(
                "Vector hit points to missing file %s — skipping (index drift)",
                vec_hit.note_path,
            )
            return None

        try:
            content = note_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Could not read %s for enrichment: %s", vec_hit.note_path, exc)
            return None

        chunks = self._chunker.chunk(vec_hit.note_path, content)
        if vec_hit.chunk_index >= len(chunks):
            logger.warning(
                "Chunk index %d out of range for %s (has %d chunks) — skipping (index drift)",
                vec_hit.chunk_index, vec_hit.note_path, len(chunks),
            )
            return None

        chunk = chunks[vec_hit.chunk_index]
        return RecallHit(
            note_path=vec_hit.note_path,
            chunk_index=vec_hit.chunk_index,
            section_title=vec_hit.section_title,
            score=vec_hit.score,
            content_preview=chunk.content[:500],
        )
