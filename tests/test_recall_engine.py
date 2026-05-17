"""Tests for segretario.flow02.recall_engine (RecallEngine facade)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from segretario.config.settings import RecallSettings
from segretario.flow02.recall_engine import RecallEngine
from segretario.recall.models import RecallEngineState, RecallHit, RecallMode, WizardType


def _make_index(tmp_path: Path) -> Path:
    meta = tmp_path / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    index = meta / "index.md"
    index.write_text("# Index\n- [[Some Note]]\n", encoding="utf-8")
    return index


# ---------------------------------------------------------------------------
# test 27
# ---------------------------------------------------------------------------

def test_recall_engine_returns_recall_result_when_enabled_and_healthy(tmp_path: Path):
    """Mock embedder+store health=True, mock retriever, check RecallResult.state == SEMANTIC_READY."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(
        enabled=True,
        db_path=tmp_path / "state" / "recall.sqlite",
    )

    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    # Patch the state machine to return SEMANTIC_READY
    with patch.object(engine._state_machine, "evaluate", return_value=(RecallEngineState.SEMANTIC_READY, None, {})):
        # Also patch the retriever so no real Ollama call happens
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            RecallHit(note_path="some/note.md", score=0.1, content_preview="preview")
        ]
        engine._retriever = mock_retriever

        result = engine.recall("test query")

    assert result.state == RecallEngineState.SEMANTIC_READY
    assert result.mode_used == RecallMode.SEMANTIC
    assert result.wizard_required is None


# ---------------------------------------------------------------------------
# test 28
# ---------------------------------------------------------------------------

def test_recall_engine_returns_wizard_when_disabled_prompt(tmp_path: Path):
    """enabled=False, dismissed=False → wizard_required = ACTIVATION."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(enabled=False, user_dismissed_wizard=False)

    engine = RecallEngine(index_path=index_path, recall_settings=settings)
    result = engine.recall("test query")

    assert result.state == RecallEngineState.SEMANTIC_DISABLED_PROMPT
    assert result.wizard_required == WizardType.ACTIVATION


# ---------------------------------------------------------------------------
# test 29
# ---------------------------------------------------------------------------

def test_recall_engine_recall_simple_returns_none_when_wizard_required(tmp_path: Path):
    """enabled=False, dismissed=False → recall_simple returns None (wizard required)."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(enabled=False, user_dismissed_wizard=False)

    engine = RecallEngine(index_path=index_path, recall_settings=settings)
    result = engine.recall_simple("test query")

    assert result is None


# ---------------------------------------------------------------------------
# test 30
# ---------------------------------------------------------------------------

def test_recall_engine_recall_simple_returns_content_when_ready(tmp_path: Path):
    """enabled=True, health OK → recall_simple returns str content."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(
        enabled=True,
        db_path=tmp_path / "state" / "recall.sqlite",
    )

    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    # Patch state machine to return SEMANTIC_READY and mock retriever
    with patch.object(engine._state_machine, "evaluate", return_value=(RecallEngineState.SEMANTIC_READY, None, {})):
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            RecallHit(note_path="some/note.md", score=0.1, content_preview="preview text")
        ]
        engine._retriever = mock_retriever

        result = engine.recall_simple("test query")

    assert result is not None
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# test 31
# ---------------------------------------------------------------------------

def test_recall_engine_keyword_search_explicit(tmp_path: Path):
    """Direct call to engine.keyword_search() with a tmp index file."""
    index_path = _make_index(tmp_path)
    # Add searchable content to index
    index_path.write_text(
        "# Index\n- [[Python Tutorial]]\n- [[Machine Learning]]\n- [[Database Notes]]\n",
        encoding="utf-8",
    )
    settings = RecallSettings(enabled=False, user_dismissed_wizard=True)
    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    result = engine.keyword_search("python tutorial")

    assert result is not None
    assert "Python" in result


# ---------------------------------------------------------------------------
# test 32
# ---------------------------------------------------------------------------

def test_recall_engine_backward_compat_no_settings(tmp_path: Path):
    """Init with just index_path (no settings) → uses RecallSettings() defaults → enabled=False → SEMANTIC_DISABLED_PROMPT."""
    index_path = _make_index(tmp_path)

    # No recall_settings argument → defaults to RecallSettings() with enabled=False
    engine = RecallEngine(index_path=index_path)
    result = engine.recall("test query")

    # Default RecallSettings has enabled=False and user_dismissed_wizard=False
    assert result.state == RecallEngineState.SEMANTIC_DISABLED_PROMPT
