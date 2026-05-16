from __future__ import annotations

from segretario.flow02.attestation import ContractVerifier
from segretario.flow02.models import RetryReason, RiskAttestation, ZarsuitOutput


class OutputGuard:
    """Wrapper sul ContractVerifier: punto di ingresso per la verifica dell'output."""

    def __init__(self, verifier: ContractVerifier | None = None) -> None:
        self._verifier = verifier or ContractVerifier()

    def verify(
        self, output: ZarsuitOutput, attestation: RiskAttestation
    ) -> tuple[bool, RetryReason | None]:
        return self._verifier.verify(output, attestation)
