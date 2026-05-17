from __future__ import annotations

from segretario.http_server.models import validate_safe_request_id


def build_context_response(payload: dict) -> dict:
    """Bit-equivalent to buildContextResponse() in zarsos-secretary-stub.mjs."""
    root = payload["secretary_context_request"]
    request_id = validate_safe_request_id(root.get("request_id"))

    return {
        "secretary_context_response": {
            "request_id": request_id,
            "status": "allowed",
            "context_payload": {
                "summary": "Segretario locale di prova: projection disponibile.",
                "constraints": [
                    "projection only",
                    "no raw private data",
                ],
            },
            "privacy_level": "sanitized",
            "cloud_safe": True,
            "usage_constraints": ["projection only"],
            "requires_output_return": False,
            "raw_included": False,
        }
    }


def build_task_response(payload: dict) -> dict:
    """Bit-equivalent to buildTaskResponse() in zarsos-secretary-stub.mjs."""
    root = payload["secretary_task_request"]
    request = root.get("request", {})
    request_id = validate_safe_request_id(request.get("request_id"))

    return {
        "secretary_task_result": {
            "version": "1.0",
            "request": {"request_id": request_id},
            "status": {
                "state": "requires_confirmation",
                "reason": "stub_draft_ready_before_final_action",
            },
            "ownership": {
                "output_owner": "segretario",
                "zarsuit_processing_allowed": False,
                "zarsuit_editing_allowed": False,
            },
            "final_response": {
                "audience": "user",
                "content": "Segretario locale di prova: bozza preparata. Serve conferma prima dell'azione finale.",
            },
            "confirmation": {
                "required": True,
                "pending_action": "stub_confirm_final_action",
            },
            "privacy": {
                "raw_private_data_exposed_to_zarsuit": False,
                "output_sanitized_by_secretary": True,
            },
            "audit": {"stored": True},
        }
    }
