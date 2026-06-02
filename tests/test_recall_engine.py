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
            RecallHit(note_path="some/note.md", chunk_index=0, section_title=None, score=0.1, content_preview="preview")
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
            RecallHit(note_path="some/note.md", chunk_index=0, section_title=None, score=0.1, content_preview="preview text")
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


# ---------------------------------------------------------------------------
# Task 3.6 — grounding knobs: RecallSettings defaults + recall_for_grounding
# ---------------------------------------------------------------------------

def test_recall_settings_grounding_knob_defaults():
    """grounding_top_k and grounding_min_score must have no-op defaults."""
    from segretario.config.settings import RecallSettings as RS
    s = RS()
    assert s.grounding_top_k is None, "grounding_top_k default must be None (no-op)"
    assert s.grounding_min_score == 0.0, "grounding_min_score default must be 0.0 (no-op)"


def test_recall_for_grounding_returns_none_when_wizard_required(tmp_path: Path):
    """recall_for_grounding must return None silently when wizard is required."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(enabled=False, user_dismissed_wizard=False)
    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    result = engine.recall_for_grounding("test query")

    assert result is None


def test_recall_for_grounding_noop_defaults_same_as_recall_simple(tmp_path: Path):
    """With default knobs (top_k=None, min_score=0.0), recall_for_grounding == recall_simple output."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(
        enabled=True,
        db_path=tmp_path / "state" / "recall.sqlite",
        grounding_top_k=None,
        grounding_min_score=0.0,
    )
    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    hits = [
        RecallHit(note_path="note.md", chunk_index=0, section_title=None, score=0.8, content_preview="contenuto A"),
        RecallHit(note_path="note.md", chunk_index=1, section_title=None, score=0.6, content_preview="contenuto B"),
    ]
    with patch.object(engine._state_machine, "evaluate", return_value=(RecallEngineState.SEMANTIC_READY, None, {})):
        engine._retriever = MagicMock()
        engine._retriever.search.return_value = hits

        result_grounding = engine.recall_for_grounding("query")
        result_simple = engine.recall_simple("query")

    assert result_grounding == result_simple


def test_recall_for_grounding_top_k_limits_search_k(tmp_path: Path):
    """grounding_top_k is passed as k to the retriever search."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(
        enabled=True,
        db_path=tmp_path / "state" / "recall.sqlite",
        grounding_top_k=2,
    )
    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    mock_retriever = MagicMock()
    mock_retriever.search.return_value = [
        RecallHit(note_path="n.md", chunk_index=0, section_title=None, score=0.9, content_preview="hit 1"),
    ]
    with patch.object(engine._state_machine, "evaluate", return_value=(RecallEngineState.SEMANTIC_READY, None, {})):
        engine._retriever = mock_retriever
        engine.recall_for_grounding("query")

    mock_retriever.search.assert_called_once_with("query", k=2)


def test_recall_for_grounding_min_score_filters_low_score_hits(tmp_path: Path):
    """Hits below grounding_min_score must be excluded from the output."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(
        enabled=True,
        db_path=tmp_path / "state" / "recall.sqlite",
        grounding_min_score=0.7,
    )
    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    hits = [
        RecallHit(note_path="n.md", chunk_index=0, section_title=None, score=0.9, content_preview="alta rilevanza"),
        RecallHit(note_path="n.md", chunk_index=1, section_title=None, score=0.4, content_preview="bassa rilevanza"),
    ]
    with patch.object(engine._state_machine, "evaluate", return_value=(RecallEngineState.SEMANTIC_READY, None, {})):
        engine._retriever = MagicMock()
        engine._retriever.search.return_value = hits
        result = engine.recall_for_grounding("query")

    assert result is not None
    assert "alta rilevanza" in result
    assert "bassa rilevanza" not in result


def test_recall_for_grounding_all_below_min_score_returns_none(tmp_path: Path):
    """If all hits are below min_score, recall_for_grounding returns None."""
    index_path = _make_index(tmp_path)
    settings = RecallSettings(
        enabled=True,
        db_path=tmp_path / "state" / "recall.sqlite",
        grounding_min_score=0.9,
    )
    engine = RecallEngine(index_path=index_path, recall_settings=settings)

    hits = [
        RecallHit(note_path="n.md", chunk_index=0, section_title=None, score=0.3, content_preview="troppo irrilevante"),
    ]
    with patch.object(engine._state_machine, "evaluate", return_value=(RecallEngineState.SEMANTIC_READY, None, {})):
        engine._retriever = MagicMock()
        engine._retriever.search.return_value = hits
        result = engine.recall_for_grounding("query")

    assert result is None
