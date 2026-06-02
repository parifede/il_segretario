"""Smoke 3.6 — qualità sintesi grounded (strumento di misura ripetibile).

Avvia prima il server:  uv run segretario http-server
Poi (stesso token):     python scripts/smoke_synthesis_quality.py

Prerequisiti:
  - Server running (127.0.0.1:8722)
  - recall.enabled=true in config, Ollama running con embedding model
  - uv run segretario recall reindex --force  (già eseguito dall'operatore prima)

Output per ogni query:
  QUERY         → testo query
  GROUNDING     → chunks recuperati dal recall (post-guard/fence), o "(nessuno)"
  RISPOSTA      → contenuto generato dal modello
  LATENZA       → secondi

Gate deterministico:
  Query "vuota" (UUID non nel vault) → grounding assente → il modello deve
  dichiarare l'assenza ("non contiene questa informazione" o "[da definire]")
  invece di inventare fatti specifici.

Placeholder queries: l'operatore sostituisce Q1-Q3 con query reali a confine
noto prima della sessione di tuning a quattro mani.
"""
from __future__ import annotations

import os
import sys
import time
import json
import httpx
from pathlib import Path

BASE_TASK = "http://127.0.0.1:8722/task"
TOKEN = os.environ.get("IL_SEGRETARIO_HTTP_TOKEN", "smoke-token-123")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# Query set
# Q1-Q3: placeholder — operatore sostituisce con query reali a confine noto
# Q4:    query sintetica garantita senza grounding (UUID non nel vault)
# ---------------------------------------------------------------------------

# fmt: off
QUERIES = [
    # (etichetta, user_visible_goal, original_input, domain, action_type)
    (
        "Q1 [placeholder — sostituire con query reale]",
        "descrivi lo stato del progetto principale",
        "dimmi dello stato del progetto",
        "vault", "read_only",
    ),
    (
        "Q2 [placeholder — sostituire con query reale]",
        "quali sono i prossimi eventi in programma",
        "quali sono i prossimi eventi",
        "vault", "read_only",
    ),
    (
        "Q3 [placeholder — sostituire con query reale]",
        "quali sono gli ultimi lavori svoli",
        "riassumi cv",
        "vault", "read_only",
    ),
    (
        "Q4 [gate deterministico — grounding vuoto]",
        "b8f2e7a1-4c3d-4f5e-9b0c-d2a6e8f3c1b7 risultati esiti date specifiche",
        "cerca b8f2e7a1-4c3d-4f5e-9b0c-d2a6e8f3c1b7",
        "vault", "read_only",
    ),
]
# fmt: on

HEDGE_MARKERS = [
    "non contiene questa informazione",
    "[da definire]",
    "non disponibile",
    "non è presente",
    "non ho informazioni",
    "nessuna informazione",
    "non trovo",
    "non risulta",
]


def _read_last_audit_events(audit_path: Path, n: int = 30) -> list[dict]:
    if not audit_path.exists():
        return []
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def _get_grounding_from_audit(audit_path: Path, request_id: str) -> dict | None:
    """Read audit event for this request_id to surface grounding metadata."""
    time.sleep(0.15)
    events = _read_last_audit_events(audit_path, n=50)
    for evt in reversed(events):
        p = evt.get("payload", evt)
        if p.get("request_id") == request_id:
            return p
    return None


def _task_body(request_id: str, goal: str, original: str, domain: str, action_type: str) -> dict:
    return {
        "secretary_task_request": {
            "version": "1.0",
            "request": {"request_id": request_id},
            "task": {"domain": domain, "action_type": action_type, "action_name": ""},
            "user_request": {
                "user_visible_goal": goal,
                "original_input": original,
            },
            "privacy": {"private_data_needed": True},
        }
    }


def _load_settings():
    from segretario.config import load_settings
    return load_settings()


def _build_recall_engine(settings):
    from segretario.flow02.recall_engine import RecallEngine
    index_path = settings.vault.path / "meta" / "index.md"
    return RecallEngine(index_path=index_path, recall_settings=settings.recall)


def _show_grounding_detail(engine, settings, query: str) -> None:
    """Print per-chunk info + assembled grounding block (post-guard/fence) for a query."""
    from segretario.flow02.recall_engine import _hits_to_text
    from segretario.http_server.context_handler import _strip_recall_headers
    from segretario.policies.grounding_guard import fence_grounding, guard_grounding
    from segretario.policies.output_guard import sanitize_user_output
    from segretario.policies.privacy import project_private_context

    recall = settings.recall
    effective_k = recall.grounding_top_k or recall.default_k
    min_score = recall.grounding_min_score

    result = engine.recall(query, k=effective_k)

    print("  CHUNKS RECUPERATI:")
    if not result.hits:
        print("    (nessun chunk)")
    else:
        for h in result.hits:
            filtered_tag = "  [FILTRATO min_score]" if (min_score > 0.0 and h.score < min_score) else ""
            preview = h.content_preview[:120].replace("\n", " ")
            print(f"    score={h.score:.3f}{filtered_tag}  {h.note_path}")
            print(f"          {preview}")
    print()

    # Reproduce pipeline identical to _ground_with_recall in task_handler
    filtered_hits = [h for h in result.hits if min_score == 0.0 or h.score >= min_score]
    raw = _hits_to_text(filtered_hits) if filtered_hits else None
    if not raw:
        print("  GROUNDING ASSEMBLATO: (nessuno)")
        print()
        return

    stripped = _strip_recall_headers(raw)
    if not stripped:
        print("  GROUNDING ASSEMBLATO: (vuoto dopo strip headers)")
        print()
        return

    try:
        projection = project_private_context(stripped)
        sanitized = sanitize_user_output(projection.text) or None
    except Exception:
        sanitized = sanitize_user_output(stripped) or None

    if not sanitized:
        print("  GROUNDING ASSEMBLATO: (vuoto dopo privacy projection)")
        print()
        return

    guard_result = guard_grounding(sanitized)
    if not guard_result.clean_text:
        print(f"  GROUNDING ASSEMBLATO: (bloccato da guard — injection_detected={guard_result.injection_detected})")
        print()
        return

    fenced = fence_grounding(guard_result.clean_text)
    print(f"  GROUNDING ASSEMBLATO (post-guard/fence | injection={guard_result.injection_detected} stripped={guard_result.segments_stripped}):")
    for line in fenced.splitlines():
        print(f"    {line}")
    print()


def _build_indexer(settings):
    from segretario.recall.chunker import H2OverlapChunker
    from segretario.recall.embedder import OllamaEmbedder
    from segretario.recall.indexer import VaultIndexer
    from segretario.recall.sqlite_vec_store import SqliteVecStore

    recall = settings.recall
    embedder = OllamaEmbedder(model=recall.embedding_model, base_url=recall.ollama_base_url)
    store = SqliteVecStore(db_path=recall.db_path, embedding_model=recall.embedding_model)
    chunker = H2OverlapChunker(max_chunk_chars=recall.embedder_max_chunk_chars)
    return VaultIndexer(
        vault_path=settings.vault.path,
        store=store,
        embedder=embedder,
        chunker=chunker,
        skip_paths=recall.skip_paths,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("=== Smoke 3.6 — qualità sintesi grounded ===\n")

# --- Load settings ---
try:
    settings = _load_settings()
    audit_path = settings.audit.events_path
    print(f"[config] vault      : {settings.vault.path}")
    print(f"[config] top_k      : {settings.recall.grounding_top_k!r}  (None = default_k={settings.recall.default_k})")
    print(f"[config] min_score  : {settings.recall.grounding_min_score}")
    print(f"[config] sync_model : {settings.llm.sync_model}")
    print()
except Exception as e:
    print(f"ERRORE: impossibile caricare settings: {e}")
    sys.exit(1)

# --- Mandatory reindex ---
print("[pre-flight] Reindex del vault (obbligatorio)...")
try:
    indexer = _build_indexer(settings)
    ri = indexer.reindex()
    print(f"             indexed={ri.indexed}, skipped={ri.skipped_unchanged}, "
          f"deleted={ri.deleted}, errors={len(ri.errors)}")
    if ri.errors:
        print(f"             ATTENZIONE errori: {ri.errors[:3]}")
except Exception as e:
    print(f"ERRORE: reindex fallito: {e}")
    sys.exit(1)

# --- Build recall engine (shares same DB as indexer) ---
try:
    recall_engine = _build_recall_engine(settings)
except Exception as e:
    print(f"ERRORE: impossibile costruire recall engine: {e}")
    sys.exit(1)

print()

# --- Auth check ---
try:
    probe = httpx.post(
        BASE_TASK,
        json={"secretary_task_request": {"request": {"request_id": "auth-probe"}}},
        timeout=5,
    )
    if probe.status_code != 401:
        print(f"ATTENZIONE: atteso 401 per no-auth, ricevuto {probe.status_code}")
except Exception:
    pass  # server may not be up; first real request will fail clearly

# ---------------------------------------------------------------------------
# Execute queries
# ---------------------------------------------------------------------------

gate_q4_ok: bool | None = None  # result of deterministc gate test

for idx, (label, goal, original, domain, action_type) in enumerate(QUERIES, 1):
    request_id = f"smoke-sq-{idx}-{int(time.time())}"
    print(f"{'-' * 70}")
    print(f"QUERY [{label}]")
    print(f"  goal     : {goal}")
    print(f"  original : {original}")
    print()

    body = _task_body(request_id, goal, original, domain, action_type)
    t0 = time.time()
    try:
        r = httpx.post(BASE_TASK, headers=HEADERS, json=body, timeout=180)
        dt = time.time() - t0
    except Exception as e:
        print(f"  ERRORE rete: {e}\n")
        continue

    print(f"  HTTP     : {r.status_code}   latenza={dt:.2f}s")

    try:
        data = r.json()
    except Exception:
        print(f"  (body non-JSON): {r.text[:400]}\n")
        continue

    res = data.get("secretary_task_result", data)
    state = res.get("status", {}).get("state", "?")
    content = (res.get("final_response", {}) or {}).get("content", "")

    print(f"  state    : {state}")

    # Audit metadata (grounding fields)
    audit_evt = _get_grounding_from_audit(audit_path, request_id)
    if audit_evt:
        inj = audit_evt.get("injection_detected", "?")
        seg = audit_evt.get("segments_stripped", "?")
        print(f"  audit    : injection_detected={inj}  segments_stripped={seg}")
    else:
        print(f"  audit    : (evento non trovato per request_id={request_id!r})")

    # Grounding detail (local — mirrors server-side pipeline without extra HTTP)
    recall_query = goal or original
    _show_grounding_detail(recall_engine, settings, recall_query)

    print("  RISPOSTA:")
    # Print full response for human review (no truncation)
    for line in content.splitlines():
        print(f"    {line}")
    if not content.strip():
        print("    (contenuto vuoto)")
    print()

    # Latency warning
    if dt > 3.0:
        print(f"  WARN: latenza {dt:.1f}s supera il budget sincrono (1-3s)")

    # --- Gate deterministico per Q4 (grounding garantito vuoto) ---
    if label.startswith("Q4"):
        content_lower = content.lower()
        found_hedge = any(marker in content_lower for marker in HEDGE_MARKERS)
        # Hard invented facts: if content contains the UUID it means it leaked
        leaked_uuid = "b8f2e7a1" in content_lower

        if leaked_uuid:
            gate_q4_ok = False
            print("  GATE Q4: FAIL — l'UUID sintetico è apparso nella risposta (leak)")
        elif found_hedge:
            gate_q4_ok = True
            found = next(m for m in HEDGE_MARKERS if m in content_lower)
            print(f"  GATE Q4: PASS — hedge presente: {found!r}")
        else:
            gate_q4_ok = None
            print("  GATE Q4: WARN — nessun hedge rilevato e nessun UUID leak.")
            print("           Rivedere la risposta manualmente.")

    print()

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("=" * 70)
print("SUMMARY")
print(f"  query eseguite : {len(QUERIES)}")
if gate_q4_ok is True:
    print("  gate Q4        : PASS (hedge con grounding vuoto)")
elif gate_q4_ok is False:
    print("  gate Q4        : FAIL (UUID sintetico presente nella risposta)")
else:
    print("  gate Q4        : WARN (revisione manuale richiesta)")
print()
print("Controlla l'audit completo:")
print(f"  Get-Content {audit_path} -Tail 20")
print()
print("Per il tuning delle manopole, modifica settings.yaml:")
print("  recall:")
print("    grounding_top_k: 3      # riduce il numero di chunk")
print("    grounding_min_score: 0.5  # filtra chunk a bassa similarità")
