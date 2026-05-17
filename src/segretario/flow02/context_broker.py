from __future__ import annotations

import uuid
from datetime import datetime, timezone

from segretario.flow02.character_store import CharacterStore
from segretario.flow02.models import (
    IntentType,
    RiskAttestation,
    SecretaryContextRequest,
)
from segretario.flow02.recall_engine import RecallEngine
from segretario.flow02.working_memory import WorkingMemory

_DEFAULT_L2_CEILING = 4_000
_MEMORY_LOOKUP_L2_CEILING = 4_000   # L2 base, recall L3 added separately
_REFINEMENT_L2_CEILING = 2_500       # Flow 02 refinement post-Zarsuit
_RECALL_L3_TOKENS = 4_000


def _l2_ceiling(intent: IntentType, retry_attempt: int) -> int:
    base = {
        IntentType.CONVERSATIONAL: _DEFAULT_L2_CEILING,
        IntentType.TASK: _DEFAULT_L2_CEILING,
        IntentType.MEMORY_LOOKUP: _MEMORY_LOOKUP_L2_CEILING,
    }.get(intent, _DEFAULT_L2_CEILING)
    return base * (2 if retry_attempt > 0 else 1)


class ContextBroker:
    """Compone il pacchetto di contesto a 3 livelli per ogni richiesta a Zarsuit."""

    def __init__(
        self,
        character_store: CharacterStore,
        working_memory: WorkingMemory,
        recall_engine: RecallEngine,
    ) -> None:
        self._character = character_store
        self._wm = working_memory
        self._recall = recall_engine

    def compose(
        self,
        *,
        request_id: str,
        session_id: str,
        attestation: RiskAttestation,
        intent: IntentType,
        goal: str,
        retry_attempt: int = 0,
    ) -> SecretaryContextRequest:
        ceiling = _l2_ceiling(intent, retry_attempt)
        wm = self._wm.with_ceiling(ceiling)
        wm.compact_if_needed()

        recall_context: str | None = None
        recall_tokens = 0
        if intent == IntentType.MEMORY_LOOKUP:
            recall_context = self._recall.recall_simple(goal, max_tokens=_RECALL_L3_TOKENS)
            recall_tokens = len(recall_context or "") // 4

        wm_tokens = wm.total_tokens()
        identity_tokens = len(self._character.identity()) // 4
        # Stima 1 token ≈ 4 char — conservative per italiano/multibyte
        total = identity_tokens + wm_tokens + recall_tokens

        return SecretaryContextRequest(
            request_id=request_id,
            internal_request_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
            character_identity=self._character.identity(),
            working_memory=wm.turns(),
            working_memory_tokens=wm_tokens,
            recall_context=recall_context,
            recall_tokens=recall_tokens,
            attestation=attestation,
            total_tokens=total,
        )
