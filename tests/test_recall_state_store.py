"""Tests for segretario.recall.state (ReindexStateStore)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from segretario.recall.state import ReindexStateStore


# ---------------------------------------------------------------------------
# test 33
# ---------------------------------------------------------------------------

def test_reindex_state_store_skips_if_recent(tmp_path: Path):
    """Set last_run to now-5min, threshold=15 → should_skip=True."""
    state_file = tmp_path / "recall_last_run.json"
    store = ReindexStateStore(state_file)

    now = datetime.now(timezone.utc)
    # Set last run 5 minutes ago
    from datetime import timedelta
    five_min_ago = now - timedelta(minutes=5)
    store.set_last_run(five_min_ago, indexed_count=10, model="mxbai-embed-large")

    should_skip = store.should_skip(now, threshold_minutes=15)
    assert should_skip is True


# ---------------------------------------------------------------------------
# test 34
# ---------------------------------------------------------------------------

def test_reindex_state_store_corrupted_file_logs_and_proceeds(tmp_path: Path, caplog):
    """Write corrupt JSON → get_last_run returns None, no exception."""
    import logging

    state_file = tmp_path / "recall_last_run.json"
    state_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

    store = ReindexStateStore(state_file)

    with caplog.at_level(logging.WARNING):
        result = store.get_last_run()

    assert result is None
    # Should have logged a warning
    assert len(caplog.records) > 0
