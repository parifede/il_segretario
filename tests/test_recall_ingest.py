"""Tests for recall invalidation hook integration in ingest."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from segretario.tools.markdown_tool import ingest_article


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    source_dir = vault / "raw" / "articles"
    source_dir.mkdir(parents=True)
    source = source_dir / "test-article.md"
    source.write_text("# Test Article\n\nSome content for testing.\n", encoding="utf-8")
    return vault


# ---------------------------------------------------------------------------
# test 37
# ---------------------------------------------------------------------------

def test_ingest_invalidates_recall_on_success(tmp_path: Path):
    """Mock _invalidate_recall; call ingest_article → verify _invalidate_recall was called."""
    vault = _make_vault(tmp_path)

    # _invalidate_recall is imported locally inside ingest_article from the hook module.
    # We track calls by patching the hook module's function, then verifying it was called.
    called_with = []

    def _fake_invalidate(vault_path, written_path):
        called_with.append((vault_path, written_path))

    with patch("segretario.recall._ingest_hook._invalidate_recall", side_effect=_fake_invalidate):
        result = ingest_article(vault, "raw/articles/test-article.md", auto=True)

    # The ingest should have succeeded
    assert result.path is not None
    # And _invalidate_recall should have been called exactly once
    assert len(called_with) == 1


# ---------------------------------------------------------------------------
# test 38
# ---------------------------------------------------------------------------

def test_ingest_does_not_fail_if_recall_invalidation_fails(tmp_path: Path):
    """Recall invalidation can fail internally without blocking ingest.

    The _invalidate_recall hook wraps all recall errors in try/except.
    We simulate a recall subsystem failure (VaultIndexer.update_note raising)
    and verify that ingest_article still completes successfully.
    """
    vault = _make_vault(tmp_path)

    # Patch indexer.update_note to raise — this simulates an Ollama/store error.
    # _invalidate_recall catches this internally, so ingest_article must not raise.
    with patch("segretario.recall.indexer.VaultIndexer.update_note", side_effect=RuntimeError("store error")):
        # load_settings is imported inside _invalidate_recall from config.loader
        # patch it at the source module
        mock_settings = MagicMock()
        mock_settings.recall.enabled = True
        mock_settings.recall.embedding_model = "mxbai-embed-large"
        mock_settings.recall.ollama_base_url = "http://127.0.0.1:11434"
        mock_settings.recall.db_path = vault / "state" / "recall.sqlite"
        mock_settings.recall.skip_paths = ["raw/elaborati"]

        with patch("segretario.config.loader.load_settings", return_value=mock_settings):
            with patch("segretario.recall.embedder.OllamaEmbedder"):
                with patch("segretario.recall.sqlite_vec_store.SqliteVecStore"):
                    # Ingest must NOT raise even if recall subsystem raises
                    result = ingest_article(vault, "raw/articles/test-article.md", auto=True)

    assert result.path is not None
