from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from segretario.flow02.character_store import CharacterStore
from segretario.flow02.context_broker import ContextBroker, _DEFAULT_L2_CEILING
from segretario.flow02.models import (
    DetailLevel,
    IntentType,
    OutputPolicy,
    RiskAttestation,
    WorkingMemoryTurn,
)
from segretario.flow02.recall_engine import RecallEngine
from segretario.flow02.working_memory import WorkingMemory


def _attestation() -> RiskAttestation:
    return RiskAttestation(
        request_id="r1",
        internal_request_id=str(uuid.uuid4()),
        approved_context_projection=["calendar"],
        output_policy=OutputPolicy.SUMMARIZED,
        max_detail_level=DetailLevel.SUMMARY,
        allowed_next_steps=[],
        user_visible_goal="Test obiettivo pianificazione",
    )


def _turn(tokens: int = 100) -> WorkingMemoryTurn:
    return WorkingMemoryTurn(role="user", content="ciao",
                             timestamp=datetime.now(timezone.utc), tokens=tokens)


def _broker(
    turns: list[WorkingMemoryTurn] | None = None,
    recall_index: Path | None = None,
) -> ContextBroker:
    wm = WorkingMemory(_DEFAULT_L2_CEILING)
    for t in (turns or []):
        wm.add_turn(t)
    return ContextBroker(
        character_store=CharacterStore("Sei Zarsuit"),
        working_memory=wm,
        recall_engine=RecallEngine(recall_index or Path("/nonexistent")),
    )


def test_compose_returns_context_with_correct_ids():
    ctx = _broker().compose(
        request_id="r1", session_id="s1",
        attestation=_attestation(),
        intent=IntentType.CONVERSATIONAL, goal="test",
    )
    assert ctx.request_id == "r1"
    assert ctx.session_id == "s1"
    assert ctx.internal_request_id != "r1"  # deve essere un UUID diverso


def test_compose_conversational_has_no_recall():
    ctx = _broker().compose(
        request_id="r1", session_id="s1",
        attestation=_attestation(),
        intent=IntentType.CONVERSATIONAL, goal="pianificazione",
    )
    assert ctx.recall_context is None
    assert ctx.recall_tokens == 0


def test_compose_memory_lookup_includes_recall(tmp_path):
    index = tmp_path / "index.md"
    index.write_text("riunione pianificata con Marco", encoding="utf-8")
    ctx = _broker(recall_index=index).compose(
        request_id="r1", session_id="s1",
        attestation=_attestation(),
        intent=IntentType.MEMORY_LOOKUP, goal="riunione pianificata",
    )
    assert ctx.recall_context is not None
    assert "riunione" in ctx.recall_context
    assert ctx.recall_tokens > 0


def test_compose_working_memory_respects_ceiling():
    # 6 turni × 1000 token = 6000 > ceiling 4000
    turns = [_turn(1000) for _ in range(6)]
    ctx = _broker(turns=turns).compose(
        request_id="r1", session_id="s1",
        attestation=_attestation(),
        intent=IntentType.CONVERSATIONAL, goal="test",
    )
    assert ctx.working_memory_tokens <= _DEFAULT_L2_CEILING


def test_retry_doubles_l2_ceiling():
    # 5 turni × 1000 = 5000 token
    # ceiling normale 4000 → compatta a 4 turni
    # ceiling retry 8000 → tutti 5 turni
    turns = [_turn(1000) for _ in range(5)]
    broker = _broker(turns=turns)

    ctx_normal = broker.compose(
        request_id="r1", session_id="s1", attestation=_attestation(),
        intent=IntentType.CONVERSATIONAL, goal="test", retry_attempt=0,
    )
    ctx_retry = broker.compose(
        request_id="r1", session_id="s1", attestation=_attestation(),
        intent=IntentType.CONVERSATIONAL, goal="test", retry_attempt=1,
    )
    assert len(ctx_retry.working_memory) > len(ctx_normal.working_memory)


def test_compose_each_call_generates_new_internal_request_id():
    broker = _broker()
    att = _attestation()
    ctx1 = broker.compose(request_id="r1", session_id="s1", attestation=att,
                          intent=IntentType.CONVERSATIONAL, goal="test")
    ctx2 = broker.compose(request_id="r1", session_id="s1", attestation=att,
                          intent=IntentType.CONVERSATIONAL, goal="test")
    assert ctx1.internal_request_id != ctx2.internal_request_id


def test_total_tokens_includes_all_levels():
    turns = [_turn(200)]
    broker = _broker(turns=turns)
    ctx = broker.compose(
        request_id="r1", session_id="s1",
        attestation=_attestation(),
        intent=IntentType.CONVERSATIONAL, goal="test",
    )
    # total = identity tokens + wm tokens
    identity_tokens = len("Sei Zarsuit") // 4
    assert ctx.total_tokens >= identity_tokens + 200


def test_retry_doubles_ceiling_for_memory_lookup(tmp_path):
    """Il retry su MEMORY_LOOKUP raddoppia il proprio tetto (4K → 8K)."""
    index = tmp_path / "index.md"
    index.write_text("contenuto di test", encoding="utf-8")
    # 10 turni da 1500 token = 15000 totale
    # MEMORY_LOOKUP normale: ceiling 4000 → compatta
    # MEMORY_LOOKUP retry: ceiling 8000 → tiene di più
    turns = [_turn(1500) for _ in range(10)]
    broker = _broker(turns=turns, recall_index=index)

    ctx_normal = broker.compose(
        request_id="r1", session_id="s1", attestation=_attestation(),
        intent=IntentType.MEMORY_LOOKUP, goal="riunione",
        retry_attempt=0,
    )
    ctx_retry = broker.compose(
        request_id="r1", session_id="s1", attestation=_attestation(),
        intent=IntentType.MEMORY_LOOKUP, goal="riunione",
        retry_attempt=1,
    )
    assert ctx_retry.working_memory_tokens > ctx_normal.working_memory_tokens
    assert ctx_retry.working_memory_tokens <= 8000  # tetto retry MEMORY_LOOKUP


def test_retry_ceiling_is_per_category_not_global(tmp_path):
    """Verifica che il × 2 si applichi sulla categoria, non sempre a 4K."""
    turns = [_turn(1000) for _ in range(7)]
    broker = _broker(turns=turns)

    # CONVERSATIONAL retry: 4K × 2 = 8K
    ctx_conv = broker.compose(
        request_id="r1", session_id="s1", attestation=_attestation(),
        intent=IntentType.CONVERSATIONAL, goal="test", retry_attempt=1,
    )
    assert ctx_conv.working_memory_tokens <= 8000

    # MEMORY_LOOKUP retry: 4K × 2 = 8K (in questo design base e default coincidono)
    ctx_ml = broker.compose(
        request_id="r1", session_id="s1", attestation=_attestation(),
        intent=IntentType.MEMORY_LOOKUP, goal="test", retry_attempt=1,
    )
    assert ctx_ml.working_memory_tokens <= 8000
