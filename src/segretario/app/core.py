from __future__ import annotations

import hashlib
import json
from typing import Any

from segretario.app.models import CoreResult, TaskRequest
from segretario.app.router import TaskRouter
from segretario.audit import AuditLog
from segretario.policies.permissions import PermissionDecision, PermissionKernel
from segretario.taskboard.payloads import TaskPayloadStore
from segretario.taskboard import TaskboardStore


class SegretarioCore:
    def __init__(
        self,
        *,
        taskboard: TaskboardStore,
        audit: AuditLog,
        router: TaskRouter,
    ) -> None:
        self.taskboard = taskboard
        self.audit = audit
        self.router = router

    def handle(self, request: TaskRequest) -> CoreResult:
        action = request.action or request.command
        decision = PermissionKernel.decision_for(action)
        task = self.taskboard.create_task(
            source=request.source,
            requested_by=request.requested_by,
            command=request.command,
            risk=request.risk,
            requires_confirmation=decision
            in {PermissionDecision.CONFIRM, PermissionDecision.PROJECT},
            confirmation_reason=_confirmation_reason(decision, action),
            input_ref=_hash_payload(request.payload),
        )
        task_id = int(task["id"])

        self.audit.append_event(
            "task.created",
            {
                "task_id": task_id,
                "command": request.command,
                "action": action,
                "permission_decision": decision.value,
            },
        )

        if decision == PermissionDecision.DENY:
            self.taskboard.deny_task(task_id, reason=f"permission denied for {action}")
            self.audit.append_event(
                "task.denied",
                {"task_id": task_id, "action": action, "reason": "permission denied"},
            )
            return CoreResult(
                ok=False,
                task_id=task_id,
                message=f"permission denied for {action}",
            )

        if decision in {PermissionDecision.CONFIRM, PermissionDecision.PROJECT}:
            payload_ref = TaskPayloadStore(
                self.taskboard.db_path.parent,
            ).save(task_id, request)
            self.taskboard.update_input_ref(task_id, payload_ref)
            self.audit.append_event(
                "task.waiting_confirmation",
                {"task_id": task_id, "action": action, "decision": decision.value},
            )
            return CoreResult(
                ok=False,
                task_id=task_id,
                message=_decision_message(decision, action),
            )

        try:
            output = self.router.agent_for(request.command).run(request)
        except Exception as exc:
            self.taskboard.record_failure(task_id, error=str(exc), max_retries=1)
            self.audit.append_event(
                "task.failed",
                {"task_id": task_id, "action": action, "error": str(exc)},
            )
            return CoreResult(ok=False, task_id=task_id, message=str(exc))

        output_ref = _safe_output_ref(output)
        self.taskboard.complete_task(task_id, output_ref=output_ref)
        self.audit.append_event(
            "task.completed",
            {"task_id": task_id, "action": action, "output": output_ref},
        )
        return CoreResult(
            ok=True,
            task_id=task_id,
            message="completed",
            output=output,
        )


def _confirmation_reason(decision: PermissionDecision, action: str) -> str | None:
    if decision == PermissionDecision.CONFIRM:
        return f"{action} requires confirmation"
    if decision == PermissionDecision.PROJECT:
        return f"{action} requires privacy projection"
    return None


def _decision_message(decision: PermissionDecision, action: str) -> str:
    if decision == PermissionDecision.CONFIRM:
        return f"{action} requires confirmation"
    if decision == PermissionDecision.PROJECT:
        return f"{action} requires privacy projection"
    return f"{action} requires permission handling"


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _safe_output_ref(output: Any) -> str:
    if isinstance(output, dict):
        for key in ("path", "report_path"):
            value = output.get(key)
            if isinstance(value, str):
                return value
    return type(output).__name__
