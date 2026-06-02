"""Real /context handler: recall + privacy projection for zarsOS bridge."""
from __future__ import annotations

import logging
import re
from typing import Any

from segretario.audit.hash_chain import AuditLog
from segretario.connectors.ollama_client import LocalModelUnavailable, OllamaClient
from segretario.flow02.models import IntentType
from segretario.flow02.recall_engine import RecallEngine
from segretario.http_server.models import validate_safe_request_id
from segretario.policies.grounding_guard import fence_grounding, guard_grounding
from segretario.policies.output_guard import sanitize_user_output
from segretario.policies.privacy import project_private_context

logger = logging.getLogger(__name__)

# Matches _hits_to_text structural header lines:
# "### path [§ section] (chunk N, score: X.XXX)"
_RECALL_HEADER_RE = re.compile(
    r"^###\s+.+\(chunk\s+\d+,\s+score:\s+[\d.]+\)\s*$",
    re.MULTILINE,
)

_SYNTHESIS_SYSTEM = (
    "Sei il Segretario. Prepari un breve contesto per Zarsuit, l'agente che parla con l'utente. "
    "In seconda persona rivolto a Zarsuit, digli in modo generale di cosa vi state occupando e a che punto siete. "
    "Resta sul generale, senza dettagli precisi. "
    "Scrivi direttamente il contesto, nient'altro. "
    "Italiano, prosa semplice, 2-3 frasi. "
    "Attieniti SOLO a ciò che il materiale di riferimento dice esplicitamente. "
    "Non collegare tra loro elementi che il materiale non collega; non dedurre date, esiti o eventi non presenti nel testo. "
    "Se il materiale è frammentario, incoerente o non risponde alla richiesta, "
    "DICHIARALO ('il materiale non contiene questa informazione') invece di costruire un ponte plausibile."
)


def _filter_forbidden_chunks(text: str, forbidden_context: list) -> str | None:
    """Discard recall chunks containing any forbidden_context term (case-insensitive).

    Returns filtered text, or None if every chunk was discarded.
    No-op when forbidden_context is empty.
    """
    terms = [str(t).lower() for t in forbidden_context if t]
    if not terms:
        return text

    header_matches = list(_RECALL_HEADER_RE.finditer(text))
    if not header_matches:
        # No structured chunks — treat whole text as one chunk
        return None if any(term in text.lower() for term in terms) else text

    prefix = text[: header_matches[0].start()]
    kept: list[str] = []
    for i, match in enumerate(header_matches):
        chunk_end = header_matches[i + 1].start() if i + 1 < len(header_matches) else len(text)
        chunk_text = text[match.start() : chunk_end]
        if not any(term in chunk_text.lower() for term in terms):
            kept.append(chunk_text)

    if not kept:
        return None
    return prefix + "".join(kept)


def _strip_recall_headers(text: str) -> str:
    """Remove structural plumbing from _hits_to_text recall output.

    Two passes:
    1. Remove the _hits_to_text structural header lines
       (### path [§ section] (chunk N, score: X.XXX)).
    2. Strip Markdown heading prefixes (#, ##, ###, ...) from content lines
       so the summary is plain prose, not formatted Markdown.
    """
    # Pass 1: structural recall headers (full lines)
    cleaned = _RECALL_HEADER_RE.sub("", text)
    # Pass 2: Markdown heading markers anywhere in the text.
    # "#{1,6} " (hash sequence + space) is always a heading marker.
    # No-space variants (C#, #hashtag, URLs with #) are not matched.
    cleaned = re.sub(r"#{1,6}\s+", "", cleaned)
    # Collapse runs of 3+ newlines to a single blank line
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _map_intent(raw: str | None) -> IntentType:
    if not raw:
        return IntentType.CONVERSATIONAL
    try:
        return IntentType(raw.lower())
    except ValueError:
        return IntentType.CONVERSATIONAL


def _synthesize_with_llm(llm_client: OllamaClient, prose: str) -> str:
    """Call local LLM for a concise privacy-safe synthesis.

    Raises LocalModelUnavailable on failure.
    """
    prompt = (
        f"Testo:\n{prose[:3000]}\n\n"
        "Riassumi in 2-3 frasi, omettendo qualsiasi informazione identificativa o sensibile."
    )
    return llm_client.generate(prompt, system=_SYNTHESIS_SYSTEM)


def build_context_projection(
    envelope: dict[str, Any],
    recall_engine: RecallEngine,
    audit_log: AuditLog,
    llm_client: OllamaClient | None = None,
) -> dict[str, Any]:
    """Build context_payload from vault via recall + synthesis + privacy projection.

    Raises ValueError for invalid request_id (caller maps → 400).
    All other failures are caught internally and returned as sanitized 'partial'.
    """
    # ValueError bubbles to handler → 400
    request_id = validate_safe_request_id(envelope.get("request_id"))

    try:
        return _project(request_id, envelope, recall_engine, audit_log, llm_client)
    except Exception as exc:
        logger.error("context projection unexpected failure: %s", exc)
        _write_audit(audit_log, "context_request_error", {
            "request_id": request_id,
            "error": "internal_error",
        })
        return _build_response(
            request_id=request_id,
            status="partial",
            summary=sanitize_user_output("Contesto temporaneamente non disponibile."),
            constraints=["projection only", "no raw private data"],
            requires_output_return=False,
        )


def _project(
    request_id: str,
    envelope: dict[str, Any],
    recall_engine: RecallEngine,
    audit_log: AuditLog,
    llm_client: OllamaClient | None,
) -> dict[str, Any]:
    user_request: str = str(envelope.get("user_request_full", "")).strip()
    intent_raw: str = str(envelope.get("intent", "conversational"))
    requested_information: list = envelope.get("requested_information") or []
    forbidden_context: list = envelope.get("forbidden_context") or []
    output_policy: str = str(envelope.get("output_policy", "")).strip()

    intent = _map_intent(intent_raw)

    # Build recall query from user request + requested_information list
    query_parts = [user_request] if user_request else []
    if isinstance(requested_information, list):
        query_parts.extend(str(x) for x in requested_information if x)
    query = " ".join(query_parts).strip() or "context"

    # Check forbidden_context: if the query hits a forbidden term → denied
    if forbidden_context:
        query_lower = query.lower()
        for item in forbidden_context:
            if item and str(item).lower() in query_lower:
                _write_audit(audit_log, "context_request_denied", {
                    "request_id": request_id,
                    "reason": "forbidden_context_match",
                    "intent": intent_raw,
                })
                return _build_response(
                    request_id=request_id,
                    status="denied",
                    summary=sanitize_user_output(
                        "Contesto non disponibile: richiesta esclusa dalla policy."
                    ),
                    constraints=["no raw private data", "forbidden context"],
                    requires_output_return=False,
                )

    # Run recall — recall_simple already handles wizard/unavailable silently
    recall_content: str | None = None
    recall_error = False
    try:
        recall_content = recall_engine.recall_for_grounding(query, max_tokens=4_000)
    except Exception as exc:
        logger.warning("recall_simple failed: %s", exc)
        recall_error = True

    # Apply forbidden_context filter to recall chunks before synthesis
    all_filtered = False
    if recall_content is not None and forbidden_context:
        filtered = _filter_forbidden_chunks(recall_content, forbidden_context)
        if filtered is None:
            all_filtered = True
            recall_content = None
        else:
            recall_content = filtered

    # Build summary + status
    base_constraints: list[str] = ["projection only", "no raw private data"]
    if output_policy:
        base_constraints.append(f"output_policy:{output_policy}")

    guard_injection_detected = False
    guard_segments_stripped = 0

    if recall_error:
        status = "partial"
        summary = sanitize_user_output(
            "Contesto parzialmente disponibile: servizio recall temporaneamente non raggiungibile."
        )
    elif all_filtered:
        status = "partial"
        summary = sanitize_user_output(
            "Contesto non disponibile entro i vincoli richiesti."
        )
    elif recall_content is None:
        # recall disabled or wizard-required → no vault content
        if intent == IntentType.MEMORY_LOOKUP:
            status = "partial"
            summary = sanitize_user_output("Contesto non trovato nel vault per questa richiesta.")
        else:
            # conversational/task without vault lookup: not an error, just no vault data
            status = "allowed"
            summary = sanitize_user_output("Nessun contesto specifico richiesto dal vault.")
    else:
        # 4-step pipeline: strip → guard → synthesize → PII tokenize → sanitize
        prose = _strip_recall_headers(recall_content)

        # Injection guard: strip suspicious paragraphs before synthesis
        guard_result = guard_grounding(prose)
        guard_injection_detected = guard_result.injection_detected
        guard_segments_stripped = guard_result.segments_stripped

        if guard_result.clean_text is None:
            status = "partial"
            summary = sanitize_user_output(
                "Contesto non disponibile entro i vincoli richiesti."
            )
        else:
            prose = guard_result.clean_text

            # Step 3: local LLM synthesis (optional — skipped when llm_client is None)
            synthesis_text = prose
            llm_failed = False
            if llm_client is not None:
                try:
                    synthesis_text = _synthesize_with_llm(llm_client, fence_grounding(prose))
                except LocalModelUnavailable as exc:
                    logger.warning("local LLM synthesis unavailable: %s", exc)
                    llm_failed = True

            if llm_failed:
                status = "partial"
                summary = sanitize_user_output(
                    "Contesto disponibile ma sintesi temporaneamente non raggiungibile."
                )
            else:
                # Step 4: PII tokenization on synthesis output
                try:
                    projection = project_private_context(synthesis_text)
                    # Step 5: mandatory output_guard pass
                    summary = sanitize_user_output(projection.text)
                except Exception as exc:
                    logger.warning("privacy projection failed: %s", exc)
                    summary = sanitize_user_output(
                        "Contesto disponibile ma proiezione non applicabile."
                    )
                status = "allowed"

    _write_audit(audit_log, "context_request_handled", {
        "request_id": request_id,
        "intent": intent_raw,
        "status": status,
        "injection_detected": guard_injection_detected,
        "segments_stripped": guard_segments_stripped,
    })

    return _build_response(
        request_id=request_id,
        status=status,
        summary=summary,
        constraints=base_constraints,
        requires_output_return=False,
    )


def _write_audit(audit_log: AuditLog, event_type: str, payload: dict[str, Any]) -> None:
    try:
        audit_log.append_event(event_type, payload)
    except Exception as exc:
        logger.warning("audit write failed: %s", exc)


def _build_response(
    *,
    request_id: str,
    status: str,
    summary: str,
    constraints: list[str],
    requires_output_return: bool,
) -> dict[str, Any]:
    cloud_safe = status in ("allowed", "partial")
    return {
        "secretary_context_response": {
            "request_id": request_id,
            "status": status,
            "context_payload": {
                "summary": summary,
                "constraints": constraints,
            },
            "cloud_safe": cloud_safe,
            "raw_included": False,
            "requires_output_return": requires_output_return,
        }
    }
