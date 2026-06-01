"""Real /task handler: classification + LLM generation + Q4 guard + audit for zarsOS bridge."""
from __future__ import annotations

import logging
from typing import Any, Iterable

from segretario.audit.hash_chain import AuditLog
from segretario.connectors.ollama_client import LocalModelUnavailable, OllamaClient
from segretario.flow02.character_store import CharacterStore
from segretario.flow02.recall_engine import RecallEngine
from segretario.http_server.context_handler import _strip_recall_headers
from segretario.http_server.models import validate_safe_request_id
from segretario.policies.output_guard import guard_zarsuit_schema_leak, sanitize_user_output
from segretario.policies.permissions import PermissionDecision, PermissionKernel as PK
from segretario.policies.privacy import project_private_context

logger = logging.getLogger(__name__)


class AuditUnavailableError(RuntimeError):
    """Raised when audit.append_event fails; signals HTTP 503 to the caller."""


# ---------------------------------------------------------------------------
# Decision tables
# ---------------------------------------------------------------------------

_REFUSED_DOMAINS: frozenset[str] = frozenset({
    "private_context_lookup",  # territory of /context, not /task
    "secret_or_forbidden",
    "dangerous_action",        # shell.execute is DENY_BY_DEFAULT
    "agent_activation",        # no remote capability
    "system_diagnostic",       # Zarsuit-handled (codex §14)
    "bacheca",                 # Taskboard not exposed via HTTP (GAP #6)
    "mixed",                   # ambiguous; clarification deferred
    "unknown",
})

# Explicit mapping (domain, action_type) → kernel constants.
# Values use PermissionKernel symbols — a wrong name is AttributeError at import,
# not a silent runtime misclassification.
# Split cells list every relevant constant; _strictest picks the tightest class.
_ACTION_MAP: dict[tuple[str, str], tuple[str, ...]] = {
    ("gmail", "read_only"):           (PK.GMAIL_READ,),
    ("gmail", "draft"):               (PK.GMAIL_DRAFT,),
    ("gmail", "external_effect"):     (PK.GMAIL_SEND, PK.GMAIL_DELETE, PK.GMAIL_ARCHIVE),
    ("calendar", "read_only"):        (PK.CALENDAR_READ,),
    ("calendar", "schedule"):         (PK.CALENDAR_SCHEDULE,),
    ("calendar", "write"):            (PK.CALENDAR_CREATE, PK.CALENDAR_CREATE_WITH_ATTENDEES, PK.CALENDAR_MODIFY),
    ("calendar", "external_effect"):  (PK.CALENDAR_DELETE, PK.CALENDAR_ACCEPT, PK.CALENDAR_DECLINE),
    ("vault", "read_only"):           (PK.VAULT_READ, PK.VAULT_SEARCH),
    ("vault", "write"):               (PK.KNOWLEDGE_WRITE, PK.SELF_PROFILE_WRITE),
    ("memory", "read_only"):          (PK.VAULT_SEARCH,),
    ("memory", "write"):              (PK.KNOWLEDGE_WRITE, PK.SELF_THOUGHTS_WRITE),
    ("web_research", "read_only"):    (PK.WEB_PUBLIC_QUERY,),
    ("vault_commands", "write"):      (PK.KNOWLEDGE_WRITE, PK.SELF_PROFILE_WRITE),
}

# Strictness order: highest number = most restrictive
_DECISION_ORDER: dict[str, int] = {
    PermissionDecision.ALLOW: 0,
    PermissionDecision.CONFIRM: 1,
    PermissionDecision.DENY: 2,
    PermissionDecision.PROJECT: 2,
}

# ---------------------------------------------------------------------------
# Content templates — never replaced by LLM on error paths
# ---------------------------------------------------------------------------

_FAILED_CONTENT_TEMPLATE = "Non è stato possibile completare il task. Riprova più tardi."
_REFUSED_CONTENT_TEMPLATE = "Mi dispiace, non posso eseguire questo tipo di operazione."

# System framing: voice only — no privacy disclaimers (guard handles that).
_TASK_SYSTEM_FRAMING = (
    "Prepara la risposta per il task utente richiesto. "
    "Usa SOLO il contesto fornito; se assente o insufficiente, dillo. "
    "Non inventare mai dati del Vault (note, progetti, date, contatti)."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strictest(decisions: Iterable[PermissionDecision]) -> PermissionDecision:
    return max(decisions, key=lambda d: _DECISION_ORDER.get(d, 2))


def _decide(domain: str, action_type: str) -> tuple[str, str, str, str]:
    """Return (state, audit_reason, mapped_action, kernel_decision).

    mapped_action is the routing key 'domain/action_type' (not the first kernel
    constant) so split-cell audit entries are readable without looking up the map.
    """
    if domain in _REFUSED_DOMAINS:
        return "refused", "refused_domain", "none", "none"

    constants = _ACTION_MAP.get((domain, action_type))
    if constants is None:
        return "refused", "unmapped_action", "none", "none"

    decision = _strictest(PK.decision_for(c) for c in constants)
    mapped_action = f"{domain}/{action_type}"  # routing key, not first kernel constant
    kernel_decision = str(decision)

    if decision == PermissionDecision.ALLOW:
        return "completed", "ok", mapped_action, kernel_decision
    if decision == PermissionDecision.CONFIRM:
        return "requires_confirmation", "ok", mapped_action, kernel_decision
    # DENY or PROJECT → refused (defensive; no current cell reaches here)
    return "refused", "kernel_denied", mapped_action, kernel_decision


def _ground_with_recall(recall_engine: RecallEngine, query: str) -> str | None:
    """Run recall + strip + privacy projection for task grounding.

    Best-effort: returns None on any failure so the caller can proceed without grounding.
    """
    try:
        raw = recall_engine.recall_simple(query, max_tokens=4000)
    except Exception as exc:
        logger.warning("recall failed for task grounding: %s", exc)
        return None
    if not raw:
        return None
    stripped = _strip_recall_headers(raw)
    if not stripped:
        return None
    try:
        projection = project_private_context(stripped)
        return sanitize_user_output(projection.text) or None
    except Exception as exc:
        logger.warning("privacy projection failed for task grounding: %s", exc)
        return sanitize_user_output(stripped) or None


def _generate_content(
    llm_client: OllamaClient,
    character_store: CharacterStore,
    domain: str,
    action_type: str,
    action_name: str,
    state: str,
    *,
    grounding: str | None = None,
) -> str:
    system = character_store.identity() + "\n" + _TASK_SYSTEM_FRAMING
    task_desc = f"{domain}/{action_type}" + (f" ({action_name})" if action_name else "")

    context_block = f"Contesto dal Vault:\n{grounding}\n\n" if grounding else ""

    if state == "requires_confirmation":
        prompt = (
            f"{context_block}"
            f"Task richiesto: {task_desc}\n"
            "Prepara una bozza e spiega che serve la conferma dell'utente prima di procedere."
        )
    else:
        prompt = (
            f"{context_block}"
            f"Task richiesto: {task_desc}\n"
            "Prepara la risposta o il risultato del task."
        )
    return llm_client.generate(prompt, system=system)


def _build_task_result(
    *,
    request_id: str,
    state: str,
    content: str,
    confirmation_required: bool,
) -> dict[str, Any]:
    return {
        "secretary_task_result": {
            "version": "1.0",
            "request": {"request_id": request_id},
            "status": {"state": state},
            "ownership": {
                "output_owner": "segretario",
                "zarsuit_processing_allowed": False,
                "zarsuit_editing_allowed": False,
            },
            "final_response": {
                "audience": "user",
                "content": content,
            },
            "confirmation": {"required": confirmation_required},
            "privacy": {
                "raw_private_data_exposed_to_zarsuit": False,
                "output_sanitized_by_secretary": True,
            },
            "audit": {"stored": True},
        }
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_task_response_real(
    envelope: dict[str, Any],
    audit_log: AuditLog,
    llm_client: OllamaClient,
    character_store: CharacterStore,
    recall_engine: RecallEngine | None = None,
) -> dict[str, Any]:
    """Build a real secretary_task_result from the secretary_task_request inner dict.

    envelope is body.secretary_task_request (the inner dict, not the outer wrapper).

    Raises:
        ValueError — invalid/missing request_id → caller maps to HTTP 400.
        AuditUnavailableError — audit write failed → caller maps to HTTP 503.
    """
    # Parse request_id — ValueError propagates to caller → HTTP 400
    request_id = validate_safe_request_id(
        envelope.get("request", {}).get("request_id")
    )

    # Defaults for audit fields (overwritten in try block on success)
    state = "failed"
    reason = "internal_error"
    mapped_action = "none"
    kernel_decision = "none"
    raw_content = _FAILED_CONTENT_TEMPLATE
    guard_fired = False

    try:
        task = envelope.get("task", {})
        domain = str(task.get("domain", "unknown")).strip() or "unknown"
        action_type = str(task.get("action_type", "unknown")).strip() or "unknown"
        action_name = str(task.get("action_name", "")).strip()

        # Recall grounding fields (correction 1)
        privacy_req = envelope.get("privacy", {}) or {}
        private_data_needed = bool(privacy_req.get("private_data_needed"))
        user_req = envelope.get("user_request", {}) or {}
        user_visible_goal = str(user_req.get("user_visible_goal", "")).strip()
        original_input = str(user_req.get("original_input", "")).strip()
        recall_query = user_visible_goal or original_input or action_name or f"{domain}/{action_type}"

        state, reason, mapped_action, kernel_decision = _decide(domain, action_type)

        if state in ("completed", "requires_confirmation"):
            grounding = None
            if private_data_needed and recall_engine is not None:
                grounding = _ground_with_recall(recall_engine, recall_query)
            raw_content = _generate_content(
                llm_client, character_store, domain, action_type, action_name, state,
                grounding=grounding,
            )
            guard_result = guard_zarsuit_schema_leak(raw_content)
            if guard_result.fired:
                guard_fired = True
                state = "failed"
                reason = "guard_fired"
                raw_content = _FAILED_CONTENT_TEMPLATE
        elif state == "refused":
            raw_content = _REFUSED_CONTENT_TEMPLATE
        # else: state=failed, raw_content already set to template

    except LocalModelUnavailable as exc:
        logger.warning("LLM unavailable for task %s: %s", request_id, exc)
        state = "failed"
        reason = "llm_unavailable"
        raw_content = _FAILED_CONTENT_TEMPLATE
    except Exception as exc:
        logger.error("task handler unexpected error for %s: %s", request_id, exc)
        # state/reason/raw_content remain at defaults set before the try

    content = sanitize_user_output(raw_content)

    # Audit — failure raises AuditUnavailableError → caller returns HTTP 503
    try:
        audit_log.append_event("secretary_task_request", {
            "request_id": request_id,
            "mapped_action": mapped_action,
            "kernel_decision": kernel_decision,
            "result_state": state,
            "output_sanitized": True,
            "guard_fired": guard_fired,
            "audit_reason": reason,
        })
    except Exception as exc:
        logger.error("audit write failed for task %s: %s", request_id, exc)
        raise AuditUnavailableError from exc

    return _build_task_result(
        request_id=request_id,
        state=state,
        content=content,
        confirmation_required=(state == "requires_confirmation"),
    )
