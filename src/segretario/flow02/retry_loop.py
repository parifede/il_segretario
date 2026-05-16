from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from segretario.flow02.context_broker import ContextBroker
from segretario.flow02.models import (
    IntentType,
    RetryAuditEvent,
    RetryOutcome,
    RetryReason,
    RiskAttestation,
    SecretaryTaskRequest,
    ZarsuitOutput,
)
from segretario.flow02.output_guard import OutputGuard
from segretario.flow02.zarsuit_client import ZarsuitClient

_MAX_RETRIES = 2
_UX_TIMEOUT_SECONDS = 3.0

_MSG_LOADING = "Zarsuit è tutto fatto, ora si riprende..."
_MSG_RETRY_2 = "ci sto ancora lavorando, un attimo"
_MSG_FAIL = "non sono riuscito a completare la richiesta"


class RetryResult:
    def __init__(
        self,
        *,
        ok: bool,
        output: ZarsuitOutput | None,
        message: str,
        audit_events: list[RetryAuditEvent],
    ) -> None:
        self.ok = ok
        self.output = output
        self.message = message
        self.audit_events = audit_events


class RetryLoop:
    def __init__(
        self,
        *,
        client: ZarsuitClient,
        guard: OutputGuard,
        broker: ContextBroker,
        on_ux_message: Callable[[str], None] | None = None,
    ) -> None:
        self._client = client
        self._guard = guard
        self._broker = broker
        self._on_ux = on_ux_message or (lambda _: None)

    def run(
        self,
        *,
        request_id: str,
        session_id: str,
        user_message: str,
        intent: IntentType,
        goal: str,
        attestation: RiskAttestation,
    ) -> RetryResult:
        audit_events: list[RetryAuditEvent] = []

        for attempt in range(_MAX_RETRIES + 1):
            # UX messages upfront for retries (not for first attempt)
            if attempt == 1:
                self._on_ux(_MSG_LOADING)
            elif attempt == 2:
                self._on_ux(_MSG_RETRY_2)

            ctx = self._broker.compose(
                request_id=request_id,
                session_id=session_id,
                attestation=attestation,
                intent=intent,
                goal=goal,
                retry_attempt=attempt,
            )
            task_req = SecretaryTaskRequest(
                context=ctx,
                user_message=user_message,
                intent_type=intent,
                user_visible_goal=goal,
            )

            t0 = time.monotonic()
            output = self._client.call(task_req)
            elapsed = time.monotonic() - t0

            # For the first attempt, show loading message only if response was slow
            if attempt == 0 and elapsed > _UX_TIMEOUT_SECONDS:
                self._on_ux(_MSG_LOADING)

            ok, reason = self._guard.verify(output, attestation)
            is_last = attempt == _MAX_RETRIES

            audit_events.append(RetryAuditEvent(
                request_id=request_id,
                internal_request_id=ctx.internal_request_id,
                attempt=attempt,
                outcome=RetryOutcome.ACCEPTED if ok else (
                    RetryOutcome.REJECTED if is_last else RetryOutcome.NEEDS_REFINEMENT
                ),
                reason=None if ok else reason,
                timestamp=datetime.now(timezone.utc),
            ))

            if ok:
                return RetryResult(
                    ok=True,
                    output=output,
                    message=output.content,
                    audit_events=audit_events,
                )

        self._on_ux(_MSG_FAIL)
        return RetryResult(
            ok=False,
            output=None,
            message=_MSG_FAIL,
            audit_events=audit_events,
        )
