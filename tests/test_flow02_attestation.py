from __future__ import annotations

import uuid

import pytest

from segretario.flow02.attestation import AttestationBuilder, ContractVerifier
from segretario.flow02.output_guard import OutputGuard
from segretario.flow02.models import (
    DetailLevel,
    OutputPolicy,
    RetryReason,
    ZarsuitOutput,
)


def _build(**kwargs):
    defaults = dict(
        request_id="r1",
        internal_request_id=str(uuid.uuid4()),
        approved_context_projection=["calendar", "contacts"],
        output_policy=OutputPolicy.SUMMARIZED,
        max_detail_level=DetailLevel.SUMMARY,
        allowed_next_steps=["schedule_meeting"],
        user_visible_goal="Pianifica una riunione con Marco",
    )
    defaults.update(kwargs)
    return AttestationBuilder().build(**defaults)


def _output(**kwargs) -> ZarsuitOutput:
    defaults = dict(
        internal_request_id=str(uuid.uuid4()),
        content="La riunione con Marco è pianificata per venerdì",
        cited_fields=["calendar"],
        suggested_next_steps=["schedule_meeting"],
        detail_level=DetailLevel.SUMMARY,
    )
    defaults.update(kwargs)
    return ZarsuitOutput(**defaults)


def test_pass_when_all_checks_ok():
    att = _build()
    out = _output()
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is True
    assert reason is None


def test_contract_violation_on_unapproved_cited_field():
    att = _build()
    out = _output(cited_fields=["calendar", "private_diary"])
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is False
    assert reason == RetryReason.CONTRACT_VIOLATION


def test_contract_violation_on_disallowed_next_step():
    att = _build()
    out = _output(suggested_next_steps=["delete_all_emails"])
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is False
    assert reason == RetryReason.CONTRACT_VIOLATION


def test_contract_violation_detail_level_too_high():
    att = _build(max_detail_level=DetailLevel.MINIMUM_NECESSARY)
    out = _output(detail_level=DetailLevel.TECHNICAL)
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is False
    assert reason == RetryReason.CONTRACT_VIOLATION


def test_detail_level_at_max_is_ok():
    att = _build(max_detail_level=DetailLevel.SUMMARY)
    out = _output(detail_level=DetailLevel.SUMMARY)
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is True


def test_goal_mismatch_when_entity_absent_from_content():
    att = _build(user_visible_goal="Pianifica riunione con Marco")
    out = _output(content="Il meteo è ottimo oggi", cited_fields=["calendar"])
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is False
    assert reason == RetryReason.GOAL_MISMATCH


def test_incomplete_output_on_empty_content():
    att = _build()
    out = _output(content="   ")
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is False
    assert reason == RetryReason.INCOMPLETE_OUTPUT


def test_boolean_only_policy_rejects_long_content():
    att = _build(output_policy=OutputPolicy.BOOLEAN_ONLY)
    out = _output(content="Sì, la riunione è " + "x" * 300)
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is False
    assert reason == RetryReason.CONTRACT_VIOLATION


def test_boolean_only_policy_accepts_short_content():
    att = _build(output_policy=OutputPolicy.BOOLEAN_ONLY)
    out = _output(content="Sì")
    ok, reason = ContractVerifier().verify(out, att)
    assert ok is True


def test_builder_populates_all_fields():
    att = AttestationBuilder().build(
        request_id="r2",
        internal_request_id="i2",
        approved_context_projection=["vault"],
        output_policy=OutputPolicy.FREE,
        max_detail_level=DetailLevel.OPERATIONAL,
        allowed_next_steps=[],
        user_visible_goal="Trova il documento X",
    )
    assert att.request_id == "r2"
    assert att.output_policy == OutputPolicy.FREE
    assert att.max_detail_level == DetailLevel.OPERATIONAL


def test_output_guard_delegates_to_verifier():
    att = _build()
    out = _output()
    guard = OutputGuard()
    ok, reason = guard.verify(out, att)
    assert ok is True
    assert reason is None


def test_output_guard_passes_failure_through():
    att = _build()
    out = _output(cited_fields=["private_diary"])
    guard = OutputGuard()
    ok, reason = guard.verify(out, att)
    assert ok is False
    assert reason == RetryReason.CONTRACT_VIOLATION
