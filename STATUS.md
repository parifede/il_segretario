# il_segretario — Status

## Flow 02: protocollo Zarsuit (fasi 1–4)

**Aggiornato:** 2026-05-17

### Stato

Fasi 1–4 completate e committate su `master`.

**Backup:**
- Branch git: `backup/pre-flow02`
- Filesystem: `E:\ZARSUIT_LOCAL_BACKUPS\il_segretario_20260516-165919`

**Suite di test:** 391 test disponibili. 38 nuovi test per Recall L3.

## Recall semantico (Task 2 — implementato 2026-05-17)

- **Modulo**: `src/segretario/recall/`
- **Modello embedding**: `mxbai-embed-large` (1024 dim) via Ollama locale
- **Storage**: `sqlite-vec` in `state/recall.sqlite` (DB separato dal taskboard)
- **Chunking**: nota intera (whole-note), un vettore per nota
- **Stato**: 5-state machine — SEMANTIC_READY, SEMANTIC_DISABLED_PROMPT, SEMANTIC_DISABLED_DISMISSED, SEMANTIC_UNAVAILABLE_TRANSIENT, SEMANTIC_DISABLED_OVERRIDE
- **Privacy**: self/ indicizzato (privacy projection = ContextBroker downstream, §3.6)
- **Re-indexing**: job schedulato (guardia 15 min) + invalidazione su ingest
- **Comandi CLI**:
  - `uv run segretario recall reindex [--force]`
  - `uv run segretario recall status`
  - `uv run segretario recall search "query" [--k 5]`
  - `uv run segretario recall reset-wizard`
- **Test**: 38 nuovi test, suite completa 391 test verdi

### Cosa è stato implementato

- **Settings** (`src/segretario/config/settings.py`): `LLMSettings.sync_model` / `async_model`, `CharacterSettings`, `ZarsuitSettings`
- **Package `flow02/`** completo:
  - `models.py` — contratti Pydantic: `RiskAttestation`, `SecretaryContextRequest`, `SecretaryTaskRequest`, `ZarsuitOutput`, `RetryAuditEvent`
  - `character_store.py` — L1 identità statica
  - `working_memory.py` — L2 sliding window con tetto adattivo per categoria (4K default / 8K su retry)
  - `recall_engine.py` — L3 recall keyword-based (stub)
  - `context_broker.py` — composizione 3 livelli, `_l2_ceiling` per categoria + retry
  - `attestation.py` — `AttestationBuilder` + `ContractVerifier` (5 check deterministici)
  - `output_guard.py` — wrapper su `ContractVerifier`
  - `zarsuit_client.py` — `ZarsuitClient` Protocol + `ZarsuitClientStub`
  - `retry_loop.py` — max 2 retry, messaggi UX, audit events per tentativo
  - `session/log.py` — JSONL append-only
  - `session/manager.py` — `Session` + `SessionManager`, doppia condizione di chiusura (`>= 24h open AND >= 60min inactive`)
  - `session/consolidation.py` — stub Fase 5 (no-op)
- **CLI:**
  - `segretario zarsuit context-request --request-id X --goal Y --intent Z`
  - `segretario session status / chat / close`

### Fuori scope (spec dedicati)

- **Fase 5**: Qwen reale + `AsyncLLMClient` (attualmente stub no-op)
- **Prompt injection detection** (§8.1 `secretary-flow02-decisions.md`)
- **Recall L3 semantico con embeddings** (§8.2 `secretary-flow02-decisions.md`)

### Bug noti / da investigare

- 2 test pre-esistenti falliti (non Flow 02): `test_work_queues_and_runs_extract_batch`, `test_repair_raw_plan_cli_limits_user_output_while_report_stays_complete` — da aprire come issue separata.

---

*Documento mantenuto a mano. Per la storia dei commit: `git log --oneline`.*
