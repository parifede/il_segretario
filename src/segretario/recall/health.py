from __future__ import annotations
import logging
from segretario.recall.embedder import OllamaEmbedder
from segretario.recall.vector_store import VectorStore

logger = logging.getLogger(__name__)


def check_embedder(embedder: OllamaEmbedder) -> tuple[bool, str]:
    """Return (is_ok, failure_reason). failure_reason is empty string if ok."""
    try:
        ok = embedder.health_check()
        if ok:
            return True, ""
        return False, f"Ollama not reachable at {embedder._base_url}"
    except Exception as exc:
        return False, str(exc)


def check_store(store: VectorStore) -> tuple[bool, str]:
    """Return (is_ok, failure_reason). failure_reason is empty string if ok."""
    try:
        ok = store.health_check()
        if ok:
            return True, ""
        return False, "sqlite-vec store health check failed"
    except Exception as exc:
        return False, str(exc)
