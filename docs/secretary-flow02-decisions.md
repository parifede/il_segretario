# Flow 02 — Decision log

Decision record for Flow 02 (Zarsuit protocol phases 1–4) and related architecture.

## 1. Settings + Config (2026-04-XX)

Unified settings model: `src/segretario/config/settings.py` with Pydantic validation.
- `LLMSettings.sync_model`, `.async_model` for Ollama
- `CharacterSettings` for secretary identity
- `ZarsuitSettings` for Zarsuit configuration
- Backward compatible YAML parsing

## 2. L1 Character Store (2026-04-XX)

Static identity L1: `src/segretario/flow02/character_store.py`
- Role, description, expertise fields
- Immutable per session
- No mutation allowed

## 3. L2 Working Memory (2026-04-XX)

Sliding window L2 memory: `src/segretario/flow02/working_memory.py`
- Per-category ceiling: 4K tokens default, 8K on retry
- Circular buffer semantics
- Adaptive sizing per conversation category

## 4. L3 Recall — Keyword-based stub (2026-05-XX)

Initial L3 recall: `src/segretario/flow02/recall_engine.py`
- Keyword-based retrieval (stub, pre-semantic)
- Placeholder for full semantic implementation

## 5. Context Broker (2026-04-XX)

Composition of 3 layers: `src/segretario/flow02/context_broker.py`
- Layer 1: character
- Layer 2: working memory
- Layer 3: L3 recall
- Per-category ceiling enforcement via `_l2_ceiling`
- Retry mode ceiling upward to 8K

## 6. Attestation + Contract Verification (2026-04-XX)

Risk attestation: `src/segretario/flow02/attestation.py`
- `AttestationBuilder` for generating `RiskAttestation` contracts
- `ContractVerifier` with 5 deterministic checks:
  1. All required fields present
  2. Audit trail coherence
  3. Token budget boundaries
  4. Zarsuit output format correctness
  5. Privacy boundary compliance (no local-only paths in public output)

## 7. Output Guard (2026-04-XX)

Output wrapper: `src/segretario/flow02/output_guard.py`
- Delegates to `ContractVerifier`
- Safe wrapper for all Zarsuit outputs

## 8. Retry Logic + Audit Trail (2026-05-XX)

Retry loop: `src/segretario/flow02/retry_loop.py`
- Max 2 retry attempts
- UX messages per attempt
- Audit events recorded for each attempt
- Session logging: `src/segretario/flow02/session/log.py` (JSONL append-only)
- Session manager: `src/segretario/flow02/session/manager.py` with dual-condition closure:
  - `>= 24h open AND >= 60min inactive`

## 9. Implementazione §8.2 (chiusa, 2026-05-17)

Recall L3 semantico implementato in Task 2. Decisioni di design finali
(dopo correzione chunking post-smoke-test, commit 516b44a):

- Approccio: Embeddings puro + architettura aperta a FTS5 futuro
- Modello: mxbai-embed-large (1024 dim, context window 512 token) via Ollama locale
- **Chunking: H2 sections con overlap 200 char + fallback split per note senza H2.**
  Target chunk ~1500 char (sicuro per 512-token context window su italiano).
  Schema DB: chunk-based (`indexed_chunks` + `chunk_vectors` vec0 cosine).
- Storage: sqlite-vec in database separato `state/recall.sqlite`
- Metric: cosine distance (distance_metric=cosine su vec0); score esposto come
  similarity = 1.0 - distance, range [0, 1], più alto = più simile.
- Pre-filtering privacy: nessuno (self/ indicizzato, privacy = broker downstream)
- Re-indexing: scheduled (skip < 15 min) + invalidazione su ingest
- State machine a 5 stati per gestire i casi reali:
  SEMANTIC_READY, SEMANTIC_DISABLED_PROMPT (wizard A),
  SEMANTIC_DISABLED_DISMISSED, SEMANTIC_UNAVAILABLE_TRANSIENT (wizard B),
  SEMANTIC_DISABLED_OVERRIDE (per-turno)

### Note storiche (patch post-smoke-test)

Il design iniziale del 2026-05-17 prevedeva "whole-note chunking" basato su
assunzione errata che mxbai-embed-large avesse context window 8192 token.
Lo smoke test ha rivelato il limite reale 512 token (~1500 char italiano):
solo 105/445 note si indicizzavano (23%). Corretti lo stesso giorno con
strategia chunking H2 + overlap (indexed=444/445 nel run finale).

Secondo bug smoke test: sqlite-vec ritornava distance grezza come score
(valori > 1.0, ordering invertito). Corretti aggiungendo metric cosine esplicito
e conversione similarity = 1.0 - distance.

Terzo bug smoke test: il CLI `recall reindex` non aggiornava `ReindexStateStore`
perché il codepath CLI era separato dal job scheduler. Lezione: verificare
TUTTI i code path del feature, non solo quello più ovvio.

## 10. Nota di design — variante doppio broker (futura)

Il design corrente affida la privacy projection a un singolo broker
(ContextBroker). In futuro si potrebbe valutare l'introduzione di un secondo
broker indipendente a valle del primo, come difesa in profondità. Vedere
`docs/recall-future-work.md` per dettagli.

## 11. TODO — Design distribuzione il_segretario + zarsOS

Domanda aperta: come distribuire `il_segretario` insieme a zarsOS?
Tre alternative discusse:
- A. Monorepo unico (un installer per entrambi)
- B. zarsOS standalone + il_segretario plug-in opzionale
- C. il_segretario embedded come dipendenza Python managed da zarsOS Node

Decisione: rivedere durante o dopo Task 4 (integrazione HTTP), quando
avremo visto come i due dialogano in pratica.
