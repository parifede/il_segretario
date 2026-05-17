from __future__ import annotations
import logging
from pathlib import Path

from segretario.recall.embedder import OllamaEmbedder, EmbedderError
from segretario.recall.models import RecallHit
from segretario.recall.vector_store import VectorStore

logger = logging.getLogger(__name__)

_PREVIEW_MAX_CHARS = 500


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

    def search(self, query: str, k: int = 5) -> list[RecallHit]:
        """Search for notes matching the query semantically.

        Returns up to k hits. Skips hits pointing to deleted files (with WARNING).
        Raises EmbedderError if query embedding fails.
        """
        query_embedding = self._embedder.embed(query)
        vec_hits = self._store.query(query_embedding, k=k)

        results: list[RecallHit] = []
        for hit in vec_hits:
            note_path = self._vault_path / hit.note_path
            if not note_path.exists():
                logger.warning(
                    "Vector hit points to missing file %s — skipping (index drift)",
                    hit.note_path,
                )
                continue
            try:
                content = note_path.read_text(encoding="utf-8", errors="replace")
                preview = _make_preview(content)
            except Exception as exc:
                logger.warning("Could not read %s for preview: %s", hit.note_path, exc)
                preview = ""
            results.append(RecallHit(
                note_path=hit.note_path,
                score=hit.score,
                content_preview=preview,
            ))
        return results


def _make_preview(content: str) -> str:
    """Return first _PREVIEW_MAX_CHARS characters without cutting wikilinks [[...]] in half."""
    if len(content) <= _PREVIEW_MAX_CHARS:
        return content
    truncated = content[:_PREVIEW_MAX_CHARS]
    # Don't cut a wikilink [[...]] in half: if we ended inside [[, back up to the [[
    last_open = truncated.rfind("[[")
    last_close = truncated.rfind("]]")
    if last_open > last_close:
        truncated = truncated[:last_open]
    elif truncated.endswith("[") and len(content) > _PREVIEW_MAX_CHARS and content[_PREVIEW_MAX_CHARS] == "[":
        # Truncation split "[[" so only the first "[" is in the slice
        truncated = truncated[:-1]
    return truncated.rstrip()
