from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from segretario.flow02.models import (
    DetailLevel,
    IntentType,
    OutputPolicy,
    RetryAuditEvent,
    RetryOutcome,
    RetryReason,
    RiskAttestation,
    SecretaryContextRequest,
    SecretaryTaskRequest,
    WorkingMemoryTurn,
    ZarsuitOutput,
)


def _make_attestation(request_id: str = "req-1") -> RiskAttestation:
    return RiskAttestation(
        request_id=request_id,
        internal_request_id=str(uuid.uuid4()),
        approved_context_projection=["calendar", "contacts"],
        output_policy=OutputPolicy.SUMMARIZED,
        max_detail_level=DetailLevel.SUMMARY,
        allowed_next_steps=["schedule_meeting"],
        user_visible_goal="Pianifica una riunione",
    )


def test_risk_attestation_has_required_fields():
    att = _make_attestation()
    assert att.request_id == "req-1"
    assert att.output_policy == OutputPolicy.SUMMARIZED
    assert att.max_detail_level == DetailLevel.SUMMARY
    assert isinstance(att.attestation_id, str)
    uuid.UUID(att.attestation_id)  # raises ValueError se non è UUID valido


def test_attestation_id_is_auto_generated():
    att1 = _make_attestation()
    att2 = _make_attestation()
    assert att1.attestation_id != att2.attestation_id


def test_secretary_context_request_internal_id_differs_from_request_id():
    att = _make_attestation(request_id="r1")
    ctx = SecretaryContextRequest(
        request_id="r1",
        internal_request_id="i1",
        session_id="s1",
        timestamp=datetime.now(timezone.utc),
        character_identity="Sei Zarsuit",
        working_memory=[],
        working_memory_tokens=0,
        recall_context=None,
        recall_tokens=0,
        attestation=att,
        total_tokens=10,
    )
    assert ctx.request_id != ctx.internal_request_id


def test_zarsuit_output_fields():
    out = ZarsuitOutput(
        internal_request_id="i1",
        content="La riunione è fissata",
        cited_fields=["calendar"],
        suggested_next_steps=["schedule_meeting"],
        detail_level=DetailLevel.SUMMARY,
    )
    assert out.raw_json is None
    assert out.detail_level == DetailLevel.SUMMARY


def test_retry_audit_event():
    ev = RetryAuditEvent(
        request_id="r1",
        internal_request_id="i2",
        attempt=1,
        outcome=RetryOutcome.NEEDS_REFINEMENT,
        reason=RetryReason.GOAL_MISMATCH,
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.attempt == 1
    assert ev.reason == RetryReason.GOAL_MISMATCH


def test_intent_type_values():
    assert IntentType.CONVERSATIONAL == "conversational"
    assert IntentType.TASK == "task"
    assert IntentType.MEMORY_LOOKUP == "memory_lookup"


def test_detail_level_values():
    assert DetailLevel.MINIMUM_NECESSARY == "minimum_necessary"
    assert DetailLevel.OPERATIONAL == "operational"
