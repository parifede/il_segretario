from __future__ import annotations

import re
from datetime import datetime, timezone

from segretario.flow02.models import (
    DetailLevel,
    OutputPolicy,
    RetryReason,
    RiskAttestation,
    ZarsuitOutput,
)

_BOOLEAN_ONLY_MAX_CHARS = 200

_DETAIL_LEVEL_ORDER = [
    DetailLevel.MINIMUM_NECESSARY,
    DetailLevel.SUMMARY,
    DetailLevel.TECHNICAL,
    DetailLevel.OPERATIONAL,
]


def _detail_index(level: DetailLevel) -> int:
    return _DETAIL_LEVEL_ORDER.index(level)


def _key_entities(goal: str) -> list[str]:
    # Cattura parole >= 4 char: "Marco" sì, sigle/pronomi no
    return [w.lower() for w in re.findall(r"\b\w{4,}\b", goal)]


class AttestationBuilder:
    def build(
        self,
        *,
        request_id: str,
        internal_request_id: str,
        approved_context_projection: list[str],
        output_policy: OutputPolicy,
        max_detail_level: DetailLevel,
        allowed_next_steps: list[str],
        user_visible_goal: str,
    ) -> RiskAttestation:
        return RiskAttestation(
            request_id=request_id,
            internal_request_id=internal_request_id,
            timestamp=datetime.now(timezone.utc),
            approved_context_projection=approved_context_projection,
            output_policy=output_policy,
            max_detail_level=max_detail_level,
            allowed_next_steps=allowed_next_steps,
            user_visible_goal=user_visible_goal,
        )


class ContractVerifier:
    """Verifica meccanica dell'output di Zarsuit contro l'attestato di rischio."""

    def verify(
        self, output: ZarsuitOutput, attestation: RiskAttestation
    ) -> tuple[bool, RetryReason | None]:
        # 1. Campi citati devono essere nel projection approvato
        unapproved = set(output.cited_fields) - set(attestation.approved_context_projection)
        if unapproved:
            return False, RetryReason.CONTRACT_VIOLATION

        # 2. Next steps devono essere nell'allow-list (se non vuota)
        if attestation.allowed_next_steps:
            disallowed = set(output.suggested_next_steps) - set(attestation.allowed_next_steps)
            if disallowed:
                return False, RetryReason.CONTRACT_VIOLATION

        # 3. detail_level <= max_detail_level
        try:
            out_idx = _detail_index(output.detail_level)
            max_idx = _detail_index(attestation.max_detail_level)
        except ValueError:
            return False, RetryReason.OUTPUT_MALFORMED
        if out_idx > max_idx:
            return False, RetryReason.CONTRACT_VIOLATION

        # 4. output_policy: per BOOLEAN_ONLY il contenuto deve essere breve
        if (
            attestation.output_policy == OutputPolicy.BOOLEAN_ONLY
            and len(output.content) > _BOOLEAN_ONLY_MAX_CHARS
        ):
            return False, RetryReason.CONTRACT_VIOLATION

        # 5. Goal mismatch: almeno un'entità chiave deve apparire nel contenuto
        # Per BOOLEAN_ONLY il contenuto è una risposta sì/no: il check entità non si applica
        if attestation.output_policy != OutputPolicy.BOOLEAN_ONLY:
            entities = _key_entities(attestation.user_visible_goal)
            if entities and not output.content.strip():
                return False, RetryReason.INCOMPLETE_OUTPUT
            if entities:
                content_lower = output.content.lower()
                if not any(e in content_lower for e in entities):
                    return False, RetryReason.GOAL_MISMATCH

        if not output.content.strip():
            return False, RetryReason.INCOMPLETE_OUTPUT

        return True, None
