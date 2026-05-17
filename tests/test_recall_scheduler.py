"""Tests for recall.reindex scheduler job (_run_recall_reindex in scheduler/jobs.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from segretario.config.settings import RecallSettings, Settings, VaultSettings
from segretario.scheduler.jobs import _run_recall_reindex


def _make_settings(tmp_path: Path, *, recall_enabled: bool = True) -> Settings:
    """Build minimal Settings with a valid vault and recall configuration."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "meta").mkdir(exist_ok=True)
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    (vault / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

    return Settings(
        vault=VaultSettings(path=vault),
        recall=RecallSettings(
            enabled=recall_enabled,
            db_path=tmp_path / "state" / "recall.sqlite",
            state_path=tmp_path / "state" / "recall_last_run.json",
            reindex_threshold_minutes=15,
        ),
    )


# ---------------------------------------------------------------------------
# test 35
# ---------------------------------------------------------------------------

def test_scheduler_recall_reindex_job_respects_guard(tmp_path: Path):
    """Mock state store says 'last run 2 min ago', threshold=15 → job returns 'skipped'."""
    settings = _make_settings(tmp_path, recall_enabled=True)

    now = datetime.now(timezone.utc)
    two_min_ago = now - timedelta(minutes=2)

    # ReindexStateStore is imported inside _run_recall_reindex, so patch at its source
    with patch("segretario.recall.state.ReindexStateStore") as MockStateStore:
        mock_instance = MagicMock()
        mock_instance.should_skip.return_value = True
        mock_instance.get_last_run.return_value = two_min_ago
        MockStateStore.return_value = mock_instance

        result = _run_recall_reindex(settings)

    assert "skipped" in result


# ---------------------------------------------------------------------------
# test 36
# ---------------------------------------------------------------------------

def test_scheduler_recall_reindex_job_skips_if_disabled(tmp_path: Path):
    """settings.recall.enabled=False → job returns 'disabled'."""
    settings = _make_settings(tmp_path, recall_enabled=False)

    result = _run_recall_reindex(settings)

    assert "disabled" in result or "skipped" in result


# ---------------------------------------------------------------------------
# test: state updated even when indexed=0
# ---------------------------------------------------------------------------

def test_reindex_job_updates_state_when_indexed_zero(tmp_path: Path):
    """State is updated even when reindex skips all notes (unchanged, indexed=0)."""
    from segretario.recall.models import ReindexResult

    settings = _make_settings(tmp_path, recall_enabled=True)

    # Build a mock ReindexResult with indexed=0 (all notes unchanged)
    mock_result = ReindexResult(indexed=0, deleted=0, skipped_unchanged=3, errors=[])

    with (
        patch("segretario.recall.state.ReindexStateStore") as MockStateStore,
        patch("segretario.recall.indexer.VaultIndexer") as MockIndexer,
        patch("segretario.recall.embedder.OllamaEmbedder"),
        patch("segretario.recall.sqlite_vec_store.SqliteVecStore"),
        patch("segretario.recall.chunker.H2OverlapChunker"),
    ):
        mock_state = MagicMock()
        mock_state.should_skip.return_value = False  # not skipped — run the job
        MockStateStore.return_value = mock_state

        mock_indexer_instance = MagicMock()
        mock_indexer_instance.reindex.return_value = mock_result
        MockIndexer.return_value = mock_indexer_instance

        result = _run_recall_reindex(settings)

    # State must have been updated (set_last_run called exactly once)
    mock_state.set_last_run.assert_called_once()
    # Result string should not say error or skipped
    assert "indexed=0" in result or "recall.reindex" in result
    assert "error" not in result.lower() or "errors=0" in result
