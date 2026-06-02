"""Task 3.6 — tests for context_handler (appended scope).

Covers:
- _SYNTHESIS_SYSTEM contains anti-confabulation constraints
- recall_for_grounding is used (not recall_simple) in _project path
- audit event carries injection_detected / segments_stripped from grounding guard
- grounding all-stripped → status partial (all_filtered branch via guard)
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from segretario.audit.hash_chain import AuditLog
from segretario.http_server.context_handler import (
    _SYNTHESIS_SYSTEM,
    build_context_projection,
)
from segretario.policies.grounding_guard import GroundingGuardResult


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeAuditLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def append_event(self, event_type: str, payload: dict[str, Any]) -> dict:
        self.events.append((event_type, payload))
        return {}


class _FakeLLMClient:
    def __init__(self, response: str = "sintesi ok") -> None:
        self._response = response

    def generate(self, prompt: str, system: str | None = None) -> str:  # noqa: ARG002
        return self._response


class _FakeRecallEngine:
    """Tracks whether recall_for_grounding was called (not recall_simple)."""

    def __init__(self, result: str | None) -> None:
        self._result = result
        self.for_grounding_calls = 0
        self.simple_calls = 0

    def recall_for_grounding(self, query: str, max_tokens: int = 4000) -> str | None:  # noqa: ARG002
        self.for_grounding_calls += 1
        return self._result

    def recall_simple(self, query: str, max_tokens: int = 4000) -> str | None:  # noqa: ARG002
        self.simple_calls += 1
        return self._result


def _envelope(*, request_id: str = "req-ch-001", intent: str = "memory_lookup") -> dict:
    return {
        "request_id": request_id,
        "user_request_full": "dimmi del progetto alpha",
        "intent": intent,
        "requested_information": ["progetto alpha"],
        "forbidden_context": [],
    }


# ---------------------------------------------------------------------------
# Test 1: _SYNTHESIS_SYSTEM contains anti-confabulation constraints
# ---------------------------------------------------------------------------

def test_synthesis_system_contains_anti_confabulation_constraints():
    """_SYNTHESIS_SYSTEM must include the three anti-confabulation phrases."""
    assert "SOLO" in _SYNTHESIS_SYSTEM, "must instruct to use ONLY what the material says"
    assert "non dedurre" in _SYNTHESIS_SYSTEM, "must prohibit inferring absent facts"
    assert "non contiene questa informazione" in _SYNTHESIS_SYSTEM, "must include hedge declaration"


# ---------------------------------------------------------------------------
# Test 2: context_handler uses recall_for_grounding, not recall_simple
# ---------------------------------------------------------------------------

def test_context_handler_uses_recall_for_grounding():
    """_project must call recall_for_grounding, not recall_simple."""
    recall = _FakeRecallEngine("contenuto del vault")
    audit = _FakeAuditLog()

    build_context_projection(_envelope(), recall, audit, llm_client=_FakeLLMClient())

    assert recall.for_grounding_calls >= 1, "recall_for_grounding must be called"
    assert recall.simple_calls == 0, "recall_simple must not be called"


# ---------------------------------------------------------------------------
# Test 3: injection detected → audit event carries correct fields
# ---------------------------------------------------------------------------

def test_context_handler_audit_injection_detected():
    """When guard detects injection, audit event must record injection_detected=True."""
    recall = _FakeRecallEngine("contenuto con payload")
    audit = _FakeAuditLog()

    with patch(
        "segretario.http_server.context_handler.guard_grounding",
        return_value=GroundingGuardResult(
            clean_text="contenuto pulito",
            injection_detected=True,
            segments_stripped=1,
        ),
    ):
        build_context_projection(_envelope(), recall, audit, llm_client=_FakeLLMClient())

    handled = [p for et, p in audit.events if et == "context_request_handled"]
    assert handled, "must have context_request_handled audit event"
    assert handled[0]["injection_detected"] is True
    assert handled[0]["segments_stripped"] == 1


# ---------------------------------------------------------------------------
# Test 4: all grounding stripped → status partial
# ---------------------------------------------------------------------------

def test_context_handler_all_grounding_stripped_returns_partial():
    """When guard strips all content (clean_text=None), status must be partial."""
    recall = _FakeRecallEngine("tutto payload injection")
    audit = _FakeAuditLog()

    with patch(
        "segretario.http_server.context_handler.guard_grounding",
        return_value=GroundingGuardResult(
            clean_text=None,
            injection_detected=True,
            segments_stripped=3,
        ),
    ):
        result = build_context_projection(_envelope(), recall, audit, llm_client=_FakeLLMClient())

    resp = result["secretary_context_response"]
    assert resp["status"] == "partial"
    assert resp["cloud_safe"] is True
