"""Tests for segretario.recall.state_machine (RecallStateMachine)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from segretario.config.settings import RecallSettings
from segretario.recall.embedder import OllamaEmbedder
from segretario.recall.models import RecallEngineState, WizardType
from segretario.recall.state_machine import RecallStateMachine
from segretario.recall.vector_store import VectorStore


def _make_sm(
    enabled: bool = False,
    dismissed: bool = False,
    embedder=None,
    store=None,
    override_mode: str | None = None,
) -> tuple[RecallEngineState, WizardType | None, dict]:
    settings = RecallSettings(enabled=enabled, user_dismissed_wizard=dismissed)
    sm = RecallStateMachine(settings, embedder=embedder, store=store)
    return sm.evaluate(override_mode=override_mode)


# ---------------------------------------------------------------------------
# test 18
# ---------------------------------------------------------------------------

def test_state_machine_disabled_first_time():
    """enabled=False, dismissed=False → SEMANTIC_DISABLED_PROMPT + WizardType.ACTIVATION."""
    state, wizard, ctx = _make_sm(enabled=False, dismissed=False)
    assert state == RecallEngineState.SEMANTIC_DISABLED_PROMPT
    assert wizard == WizardType.ACTIVATION


# ---------------------------------------------------------------------------
# test 19
# ---------------------------------------------------------------------------

def test_state_machine_disabled_dismissed():
    """enabled=False, dismissed=True → SEMANTIC_DISABLED_DISMISSED, wizard=None."""
    state, wizard, ctx = _make_sm(enabled=False, dismissed=True)
    assert state == RecallEngineState.SEMANTIC_DISABLED_DISMISSED
    assert wizard is None


# ---------------------------------------------------------------------------
# test 20
# ---------------------------------------------------------------------------

def test_state_machine_enabled_healthy():
    """enabled=True, both health checks ok → SEMANTIC_READY, wizard=None."""
    embedder = MagicMock(spec=OllamaEmbedder)
    embedder.health_check.return_value = True
    embedder._base_url = "http://127.0.0.1:11434"

    store = MagicMock()
    store.health_check.return_value = True

    settings = RecallSettings(enabled=True)
    sm = RecallStateMachine(settings, embedder=embedder, store=store)
    state, wizard, ctx = sm.evaluate()

    assert state == RecallEngineState.SEMANTIC_READY
    assert wizard is None


# ---------------------------------------------------------------------------
# test 21
# ---------------------------------------------------------------------------

def test_state_machine_enabled_embedder_down():
    """enabled=True, embedder health fails → SEMANTIC_UNAVAILABLE_TRANSIENT + WizardType.DOWNGRADE."""
    embedder = MagicMock(spec=OllamaEmbedder)
    embedder.health_check.return_value = False
    embedder._base_url = "http://127.0.0.1:11434"

    store = MagicMock()
    store.health_check.return_value = True

    settings = RecallSettings(enabled=True)
    sm = RecallStateMachine(settings, embedder=embedder, store=store)
    state, wizard, ctx = sm.evaluate()

    assert state == RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT
    assert wizard == WizardType.DOWNGRADE


# ---------------------------------------------------------------------------
# test 22
# ---------------------------------------------------------------------------

def test_state_machine_enabled_store_down():
    """enabled=True, store health fails → SEMANTIC_UNAVAILABLE_TRANSIENT + WizardType.DOWNGRADE."""
    embedder = MagicMock(spec=OllamaEmbedder)
    embedder.health_check.return_value = True
    embedder._base_url = "http://127.0.0.1:11434"

    store = MagicMock()
    store.health_check.return_value = False

    settings = RecallSettings(enabled=True)
    sm = RecallStateMachine(settings, embedder=embedder, store=store)
    state, wizard, ctx = sm.evaluate()

    assert state == RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT
    assert wizard == WizardType.DOWNGRADE


# ---------------------------------------------------------------------------
# test 23
# ---------------------------------------------------------------------------

def test_state_machine_override_keyword_once():
    """override_mode='keyword_once' → SEMANTIC_DISABLED_OVERRIDE, wizard=None."""
    state, wizard, ctx = _make_sm(override_mode="keyword_once")
    assert state == RecallEngineState.SEMANTIC_DISABLED_OVERRIDE
    assert wizard is None


# ---------------------------------------------------------------------------
# test 24
# ---------------------------------------------------------------------------

def test_state_machine_override_keyword_proceed():
    """override_mode='keyword_proceed' → SEMANTIC_UNAVAILABLE_TRANSIENT, wizard=None."""
    state, wizard, ctx = _make_sm(override_mode="keyword_proceed")
    assert state == RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT
    assert wizard is None


# ---------------------------------------------------------------------------
# test 25
# ---------------------------------------------------------------------------

def test_state_machine_wizard_context_activation_has_required_fields():
    """ACTIVATION wizard context has 'description', 'performance_note', 'model'."""
    state, wizard, ctx = _make_sm(enabled=False, dismissed=False)
    assert state == RecallEngineState.SEMANTIC_DISABLED_PROMPT
    assert "description" in ctx
    assert "performance_note" in ctx
    assert "model" in ctx


# ---------------------------------------------------------------------------
# test 26
# ---------------------------------------------------------------------------

def test_state_machine_wizard_context_downgrade_has_failure_reason():
    """DOWNGRADE wizard context has 'failure_reason'."""
    embedder = MagicMock(spec=OllamaEmbedder)
    embedder.health_check.return_value = False
    embedder._base_url = "http://127.0.0.1:11434"

    store = MagicMock()
    store.health_check.return_value = True

    settings = RecallSettings(enabled=True)
    sm = RecallStateMachine(settings, embedder=embedder, store=store)
    state, wizard, ctx = sm.evaluate()

    assert state == RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT
    assert "failure_reason" in ctx
