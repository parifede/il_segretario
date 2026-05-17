"""Tests that CLI 'recall reindex' updates the state store."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from segretario.cli import app
from segretario.recall.embedder import OllamaEmbedder
from segretario.recall.state import ReindexStateStore


def _make_minimal_vault(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal vault with one note and return (vault_path, state_path)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "meta").mkdir()
    (vault / "meta" / "index.md").write_text("# Index", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log", encoding="utf-8")
    (vault / "AGENTS.md").write_text("# Agents", encoding="utf-8")
    (vault / "test.md").write_text("# Test note\n\nSome content.", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return vault, state_dir


def _make_config(tmp_path: Path, vault: Path, state_dir: Path) -> Path:
    """Write a minimal segretario.yaml for the test."""
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
vault:
  path: {vault.as_posix()}
recall:
  enabled: true
  db_path: {(state_dir / "recall.sqlite").as_posix()}
  state_path: {(state_dir / "recall_last_run.json").as_posix()}
""",
        encoding="utf-8",
    )
    return config


@pytest.fixture()
def _mock_embedder():
    """Patch OllamaEmbedder so no real Ollama call is made."""
    fake_embedding = [0.1] * 1024
    with patch("segretario.recall.embedder.OllamaEmbedder") as mock_cls:
        instance = MagicMock(spec=OllamaEmbedder)
        instance.embed.return_value = fake_embedding
        instance.health_check.return_value = True
        mock_cls.return_value = instance
        yield instance


def test_cli_recall_reindex_creates_state_file(tmp_path, monkeypatch, _mock_embedder):
    """CLI 'recall reindex' must create recall_last_run.json after success."""
    vault, state_dir = _make_minimal_vault(tmp_path)
    config = _make_config(tmp_path, vault, state_dir)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    state_path = state_dir / "recall_last_run.json"
    assert not state_path.exists()

    runner = CliRunner()
    result = runner.invoke(app, ["recall", "reindex"])
    assert result.exit_code == 0, result.output

    assert state_path.exists(), "state file must be created after reindex"
    store = ReindexStateStore(state_path)
    last = store.get_last_run()
    assert last is not None
    assert isinstance(last, datetime)


def test_cli_recall_status_shows_timestamp_after_reindex(tmp_path, monkeypatch, _mock_embedder):
    """After 'recall reindex', 'recall status' must show ISO timestamp, not 'never'."""
    vault, state_dir = _make_minimal_vault(tmp_path)
    config = _make_config(tmp_path, vault, state_dir)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    runner = CliRunner()
    runner.invoke(app, ["recall", "reindex"])

    # status checks embedder health — also patch that so it doesn't fail
    with patch("segretario.recall.embedder.OllamaEmbedder") as mock_cls:
        instance = MagicMock(spec=OllamaEmbedder)
        instance.health_check.return_value = True
        mock_cls.return_value = instance
        with patch("segretario.recall.health.check_embedder", return_value=(True, "ok")):
            with patch("segretario.recall.health.check_store", return_value=(True, "ok")):
                result = runner.invoke(app, ["recall", "status"])

    assert result.exit_code == 0, result.output
    assert "never" not in result.output, f"'never' found in status output: {result.output}"
    assert "Last reindex:" in result.output


def test_cli_recall_reindex_updates_state_when_all_unchanged(tmp_path, monkeypatch, _mock_embedder):
    """State is updated even when reindex skips all unchanged notes."""
    vault, state_dir = _make_minimal_vault(tmp_path)
    config = _make_config(tmp_path, vault, state_dir)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    runner = CliRunner()
    runner.invoke(app, ["recall", "reindex"])  # first run: indexes

    state_path = state_dir / "recall_last_run.json"
    assert state_path.exists(), "state file must exist after first reindex"
    first_mtime = state_path.stat().st_mtime

    time.sleep(0.05)
    runner.invoke(app, ["recall", "reindex"])  # second run: all unchanged

    second_mtime = state_path.stat().st_mtime
    assert second_mtime > first_mtime, "state file must be updated even when indexed=0"
