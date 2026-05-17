"""Recall invalidation hook — called after successful vault writes.

This module provides a single helper ``_invalidate_recall`` that updates the
recall index for a single note immediately after ingest.  All failures are
swallowed so that ingest is never blocked by recall unavailability.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _invalidate_recall(vault_path: Path, written_path: Path) -> None:
    """Best-effort recall index update for *written_path* inside *vault_path*.

    The function is a no-op when recall is disabled in settings.
    Any exception from the recall subsystem is caught, logged at WARNING
    level, and suppressed — ingest MUST NOT fail due to recall errors.
    """
    try:
        from segretario.config.loader import load_settings

        settings = load_settings()
    except Exception as exc:
        logger.warning(
            "recall invalidation skipped — could not load settings: %s", exc
        )
        return

    if not settings.recall.enabled:
        return

    try:
        from segretario.recall.indexer import VaultIndexer
        from segretario.recall.embedder import OllamaEmbedder
        from segretario.recall.sqlite_vec_store import SqliteVecStore
        from segretario.recall.chunker import WholeNoteChunker

        embedder = OllamaEmbedder(
            model=settings.recall.embedding_model,
            base_url=settings.recall.ollama_base_url,
        )
        store = SqliteVecStore(
            db_path=settings.recall.db_path,
            embedding_model=settings.recall.embedding_model,
        )
        indexer = VaultIndexer(
            vault_path=vault_path,
            store=store,
            embedder=embedder,
            chunker=WholeNoteChunker(),
            skip_paths=settings.recall.skip_paths,
        )
        indexer.update_note(written_path)
    except Exception as exc:
        logger.warning(
            "recall update_note failed for %s: %s. "
            "Next scheduled reindex will catch up.",
            written_path,
            exc,
        )
