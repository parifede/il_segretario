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
    SecretaryTaskRequest,
)
from segretario.flow02.recall_engine import RecallEngine
from segretario.flow02.working_memory import WorkingMemory
from segretario.flow02.zarsuit_client import ZarsuitClientStub


def _task_request(goal: str = "Pianifica riunione") -> SecretaryTaskRequest:
    att = AttestationBuilder().build(
        request_id="r1",
        internal_request_id=str(uuid.uuid4()),
        approved_context_projection=["calendar"],
        output_policy=OutputPolicy.SUMMARIZED,
        max_detail_level=DetailLevel.SUMMARY,
        allowed_next_steps=["schedule_meeting"],
        user_visible_goal=goal,
    )
    broker = ContextBroker(
        CharacterStore("Sei Zarsuit"),
        WorkingMemory(4000),
        RecallEngine(Path("/nonexistent")),
    )
    ctx = broker.compose(
        request_id="r1", session_id="s1",
        attestation=att,
        intent=IntentType.CONVERSATIONAL, goal=goal,
    )
    return SecretaryTaskRequest(context=ctx, user_message="Pianifica",
                                intent_type=IntentType.CONVERSATIONAL,
                                user_visible_goal=goal)


def test_stub_returns_default_response_when_no_responses_configured():
    stub = ZarsuitClientStub()
    req = _task_request()
    out = stub.call(req)
    assert out.content.startswith("[stub]")
    assert out.internal_request_id == req.context.internal_request_id


def test_stub_returns_configured_response():
    stub = ZarsuitClientStub()
    stub.add_response(
        content="riunione pianificata con Marco",
        cited_fields=["calendar"],
        suggested_next_steps=["schedule_meeting"],
        detail_level=DetailLevel.SUMMARY,
    )
    req = _task_request()
    out = stub.call(req)
    assert out.content == "riunione pianificata con Marco"
    assert out.cited_fields == ["calendar"]


def test_stub_cycles_through_multiple_responses():
    stub = ZarsuitClientStub()
    stub.add_response(content="prima risposta", cited_fields=[])
    stub.add_response(content="seconda risposta", cited_fields=[])
    req = _task_request()
    out1 = stub.call(req)
    out2 = stub.call(req)
    assert out1.content == "prima risposta"
    assert out2.content == "seconda risposta"


def test_stub_last_response_repeated_after_exhaustion():
    stub = ZarsuitClientStub()
    stub.add_response(content="unica risposta", cited_fields=[])
    req = _task_request()
    out1 = stub.call(req)
    out2 = stub.call(req)
    assert out1.content == out2.content == "unica risposta"
