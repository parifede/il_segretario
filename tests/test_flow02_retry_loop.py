from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from segretario.flow02.attestation import AttestationBuilder
from segretario.flow02.character_store import CharacterStore
from segretario.flow02.context_broker import ContextBroker
from segretario.flow02.models import (
    DetailLevel,
    IntentType,
    OutputPolicy,
    RetryOutcome,
    RetryReason,
)
from segretario.flow02.output_guard import OutputGuard
from segretario.flow02.recall_engine import RecallEngine
from segretario.flow02.retry_loop import (
    RetryLoop,
    _MAX_RETRIES,
    _MSG_FAIL,
    _MSG_LOADING,
    _MSG_RETRY_2,
)
from segretario.flow02.working_memory import WorkingMemory
from segretario.flow02.zarsuit_client import ZarsuitClientStub


def _broker() -> ContextBroker:
    return ContextBroker(
        CharacterStore("Sei Zarsuit"),
        WorkingMemory(4000),
        RecallEngine(Path("/nonexistent")),
    )


def _attestation():
    return AttestationBuilder().build(
        request_id="r1",
        internal_request_id=str(uuid.uuid4()),
        approved_context_projection=["calendar"],
        output_policy=OutputPolicy.SUMMARIZED,
        max_detail_level=DetailLevel.SUMMARY,
        allowed_next_steps=["schedule_meeting"],
        user_visible_goal="Pianifica riunione",
    )


def _run(stub: ZarsuitClientStub, ux_messages: list[str] | None = None):
    messages = ux_messages if ux_messages is not None else []
    loop = RetryLoop(
        client=stub,
        guard=OutputGuard(),
        broker=_broker(),
        on_ux_message=messages.append,
    )
    return loop.run(
        request_id="r1", session_id="s1",
        user_message="Pianifica una riunione",
        intent=IntentType.CONVERSATIONAL,
        goal="Pianifica riunione",
        attestation=_attestation(),
    )


def test_success_on_first_attempt():
    stub = ZarsuitClientStub()
    stub.add_response(
        content="riunione pianificata",
        cited_fields=["calendar"],
        suggested_next_steps=["schedule_meeting"],
        detail_level=DetailLevel.SUMMARY,
    )
    result = _run(stub)
    assert result.ok is True
    assert len(result.audit_events) == 1
    assert result.audit_events[0].outcome == RetryOutcome.ACCEPTED
    assert result.audit_events[0].attempt == 0


def test_success_on_second_attempt():
    stub = ZarsuitClientStub()
    stub.add_response(content="niente di utile", cited_fields=["calendar"])
    stub.add_response(
        content="riunione pianificata",
        cited_fields=["calendar"],
        suggested_next_steps=["schedule_meeting"],
        detail_level=DetailLevel.SUMMARY,
    )
    messages = []
    result = _run(stub, messages)
    assert result.ok is True
    assert len(result.audit_events) == 2
    assert result.audit_events[0].outcome == RetryOutcome.NEEDS_REFINEMENT
    assert result.audit_events[0].reason == RetryReason.GOAL_MISMATCH
    assert result.audit_events[1].outcome == RetryOutcome.ACCEPTED
    assert _MSG_LOADING in messages


def test_fail_after_max_retries():
    stub = ZarsuitClientStub()
    for _ in range(_MAX_RETRIES + 1):
        stub.add_response(content="niente", cited_fields=["calendar"])
    messages = []
    result = _run(stub, messages)
    assert result.ok is False
    assert result.message == _MSG_FAIL
    assert len(result.audit_events) == _MAX_RETRIES + 1
    assert result.audit_events[-1].outcome == RetryOutcome.REJECTED
    assert _MSG_FAIL in messages


def test_each_attempt_has_distinct_internal_request_id():
    stub = ZarsuitClientStub()
    for _ in range(_MAX_RETRIES + 1):
        stub.add_response(content="niente", cited_fields=["calendar"])
    result = _run(stub)
    ids = [ev.internal_request_id for ev in result.audit_events]
    assert len(set(ids)) == len(ids)


def test_ux_message_loading_on_first_retry():
    stub = ZarsuitClientStub()
    stub.add_response(content="niente", cited_fields=["calendar"])
    stub.add_response(
        content="riunione pianificata",
        cited_fields=["calendar"],
        suggested_next_steps=["schedule_meeting"],
        detail_level=DetailLevel.SUMMARY,
    )
    messages = []
    result = _run(stub, messages)
    assert result.ok is True
    assert _MSG_LOADING in messages


def test_ux_message_retry_2_on_second_retry():
    stub = ZarsuitClientStub()
    stub.add_response(content="niente 1", cited_fields=["calendar"])
    stub.add_response(content="niente 2", cited_fields=["calendar"])
    stub.add_response(
        content="riunione pianificata",
        cited_fields=["calendar"],
        suggested_next_steps=["schedule_meeting"],
        detail_level=DetailLevel.SUMMARY,
    )
    messages = []
    result = _run(stub, messages)
    assert result.ok is True
    assert _MSG_RETRY_2 in messages


def test_request_id_unchanged_across_retries():
    stub = ZarsuitClientStub()
    for _ in range(_MAX_RETRIES + 1):
        stub.add_response(content="niente", cited_fields=["calendar"])
    result = _run(stub)
    for ev in result.audit_events:
        assert ev.request_id == "r1"
