"""Task 3.6 — tests for task_handler (appended scope).

Covers:
- audit event includes injection_detected / segments_stripped from grounding guard
- clean_text=None path: _generate_content called with grounding=None
- _TASK_SYSTEM_FRAMING contains anti-confabulation / hedge constraints
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from segretario.http_server.task_handler import (
    _TASK_SYSTEM_FRAMING,
    build_task_response_real,
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
    def __init__(self, response: str = "risposta ok") -> None:
        self._response = response
        self.last_prompt: str | None = None
        self.last_system: str | None = None

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.last_prompt = prompt
        self.last_system = system
        return self._response


class _FakeCharacterStore:
    def identity(self) -> str:
        return "Sei Zarsuit."


class _FakeRecallEngine:
    def __init__(self, result: str | None) -> None:
        self._result = result

    def recall_for_grounding(self, query: str, max_tokens: int = 4000) -> str | None:  # noqa: ARG002
        return self._result


def _minimal_envelope(*, private_data_needed: bool = False) -> dict:
    return {
        "request": {"request_id": "req-th-001"},
        "task": {"domain": "vault", "action_type": "read_only", "action_name": ""},
        "user_request": {"original_input": "cerca note", "user_visible_goal": "trovare note"},
        "privacy": {"private_data_needed": private_data_needed},
    }


# ---------------------------------------------------------------------------
# Test 1: audit event carries injection_detected and segments_stripped
# ---------------------------------------------------------------------------

def test_task_handler_audit_injection_detected_true():
    """When recall returns content with an injection payload, audit event records it."""
    audit = _FakeAuditLog()
    llm = _FakeLLMClient()
    recall = _FakeRecallEngine("contenuto pulito del vault")

    with patch(
        "segretario.http_server.task_handler.guard_grounding",
        return_value=GroundingGuardResult(
            clean_text="contenuto pulito del vault",
            injection_detected=True,
            segments_stripped=1,
        ),
    ):
        build_task_response_real(
            _minimal_envelope(private_data_needed=True),
            audit,
            llm,
            _FakeCharacterStore(),
            recall_engine=recall,
        )

    task_events = [p for et, p in audit.events if et == "secretary_task_request"]
    assert task_events, "audit must have a secretary_task_request event"
    payload = task_events[0]
    assert payload["injection_detected"] is True
    assert payload["segments_stripped"] == 1


# ---------------------------------------------------------------------------
# Test 2: clean_text=None → _generate_content called with grounding=None
# ---------------------------------------------------------------------------

def test_task_handler_all_payload_stripped_no_grounding_in_prompt():
    """When guard strips all content (clean_text=None), LLM prompt must not contain a fence."""
    audit = _FakeAuditLog()
    llm = _FakeLLMClient()
    recall = _FakeRecallEngine("qualcosa che sarà tutto strippato")

    with patch(
        "segretario.http_server.task_handler.guard_grounding",
        return_value=GroundingGuardResult(
            clean_text=None,
            injection_detected=True,
            segments_stripped=2,
        ),
    ):
        build_task_response_real(
            _minimal_envelope(private_data_needed=True),
            audit,
            llm,
            _FakeCharacterStore(),
            recall_engine=recall,
        )

    # LLM must have been called (task still executes)
    assert llm.last_prompt is not None
    # No fence delimiters should appear in the prompt (grounding=None path)
    assert "INIZIO MATERIALE DI RIFERIMENTO" not in llm.last_prompt
    assert "FINE MATERIALE DI RIFERIMENTO" not in llm.last_prompt

    task_events = [p for et, p in audit.events if et == "secretary_task_request"]
    assert task_events[0]["injection_detected"] is True
    assert task_events[0]["segments_stripped"] == 2


# ---------------------------------------------------------------------------
# Test 3: _TASK_SYSTEM_FRAMING contains anti-confabulation constraints
# ---------------------------------------------------------------------------

def test_task_system_framing_contains_anti_confabulation_constraints():
    """_TASK_SYSTEM_FRAMING must include the three anti-confabulation constraints."""
    assert "SOLO" in _TASK_SYSTEM_FRAMING, "must instruct to use ONLY what the material says"
    assert "non dedurre" in _TASK_SYSTEM_FRAMING, "must prohibit inferring absent facts"
    assert "non contiene questa informazione" in _TASK_SYSTEM_FRAMING, "must include hedge declaration"


# ---------------------------------------------------------------------------
# Test 4: audit defaults when private_data_needed=False (no recall)
# ---------------------------------------------------------------------------

def test_task_handler_audit_defaults_when_no_recall():
    """When private_data_needed is False, audit must have injection_detected=False, segments_stripped=0."""
    audit = _FakeAuditLog()
    llm = _FakeLLMClient()
    recall = _FakeRecallEngine(None)

    build_task_response_real(
        _minimal_envelope(private_data_needed=False),
        audit,
        llm,
        _FakeCharacterStore(),
        recall_engine=recall,
    )

    task_events = [p for et, p in audit.events if et == "secretary_task_request"]
    assert task_events, "audit must have a secretary_task_request event"
    payload = task_events[0]
    assert payload["injection_detected"] is False
    assert payload["segments_stripped"] == 0
