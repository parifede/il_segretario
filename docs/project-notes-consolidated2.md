# `il_segretario` — Note di progetto consolidate

> Documento vivo. Da aggiornare a ogni chiusura di task o decisione importante.
>
> Posizionalo in: `E:\il_segretario\docs\project-notes-consolidated.md`
>
> Ultimo aggiornamento: 2026-05-17 sera (post-merge Task 2 e Task 3b-1)

---

## 1. Piano completo dei task

- ✅ **Task 1**: Fix scheduling temporale backup — chiuso, **mergeato su master** (`43b4533`)
- ✅ **Task 2**: Recall L3 semantico via embeddings + state machine — chiuso, **mergeato su master**
  - Commits originali su `feature/task2-recall-semantic`: `516b44a` + `08f9e09`
  - 420 test verdi
  - 4 round di patch necessari (chunking H2, score similarity, state, CLI)
  - Smoke test: 444/445 note indicizzate, score [0,1], ordering semantico corretto
- ✅ **Task 3b-1**: Server HTTP stub-equivalent — chiuso, **mergeato su master** (`891dc33`)
  - Originale su `feature/task3b1-http-server`: commit `71306ff`
  - 20 nuovi test (440 totali nel repo)
  - Smoke test passato 8/8 step
  - FastAPI + uvicorn, bind solo 127.0.0.1:8722
  - Drop-in replacement di `zarsos-secretary-stub.mjs` lato zarsOS

- 🔲 **Task 3a**: Gateway HTTP zarsOS *(altra chat, Node.js)*
  - Spec: `zarsOS_HTTP_documento_finale.md` + `zarsOS_HTTP_design_notes.md`
  - Done criteria: `S1-S9_done_criteria.md`
  - Endpoint zarsOS: `POST /v1/request` su `127.0.0.1:8721` e overlay tailnet
  - Auth: Bearer device-paired

- 🔲 **Task 3b-2**: Logica reale per `/context` e `/task`
  - Sostituisce le risposte hardcoded di Task 3b-1
  - Userà `RecallEngine` di Task 2 (ora disponibile in master) + broker veri
  - Endpoint: stessi di Task 3b-1, comportamento aggiornato

- 🔲 **Task 3c**: Smoke test integrazione end-to-end zarsOS ↔ il_segretario
  - zarsOS chiama il_segretario reale via HTTP localhost
  - Verifica privacy projection, retry loop, messaggio fallback su timeout 3s

- 🔲 **Task 3.5**: Prompt injection detection
  - Da fare DOPO Task 3c
  - Opzioni: regex/keyword, schema strutturale, LLM classifier Gemma. Combo proposta.

- 🔲 **Task 4**: Wizard UX in zarsOS (lato JavaScript)
  - Sfrutta `RecallResult.wizard_required` esposto in Task 2
  - ACTIVATION e DOWNGRADE wizards

- 🔲 **Task 5**: Documentazione utente operativa

---

## 2. Decisioni di design chiuse (cronologia)

### Task 1 (Fix scheduling backup) — 2026-05-17

1. Skip rappresentato come `BackupResult(ok=True, path=None, message="skipped: ...")`. Non è un errore.
2. Soglie configurabili (`weekly_threshold_days`=7, `monthly_threshold_days`=30).
3. File state corrotto → WARNING + procede come "mai eseguito".
4. Manual backup mai sotto guardia.
5. `BackupStateStore` separato da `BackupManager`.
6. Write atomico (temp + replace).

### Task 2 (Recall L3) — 2026-05-17

**Round 1 (design iniziale):**

1. Embeddings puro + architettura aperta a FTS5 futuro
2. Modello: `mxbai-embed-large` (1024 dim, 512 token context)
3. Storage: `sqlite-vec` in `state/recall.sqlite`
4. No pre-filtering privacy (broker downstream gestisce)
5. Re-indexing: scheduled (skip < 15 min) + invalidazione su ingest
6. State machine 5 stati: SEMANTIC_READY, SEMANTIC_DISABLED_PROMPT, SEMANTIC_DISABLED_DISMISSED, SEMANTIC_UNAVAILABLE_TRANSIENT, SEMANTIC_DISABLED_OVERRIDE
7. `RecallEngine` API: `recall()`, `recall_simple()`, `keyword_search()`
8. Defensive default `enabled=False`
9. `user_dismissed_wizard` flag

**Round 2 (patch chunking H2):**

10. Chunking H2 con overlap 200 char tra chunk e tra sezioni H2
11. Note senza H2 ≤1500 char → 1 chunk; >1500 char → split con overlap
12. Target chunk: 1500 char (sicuro per 512-token mxbai)
13. `RecallHit` ha `chunk_index` e `section_title`
14. Schema: `indexed_chunks` + `chunk_vectors`

**Round 3 (patch score):**

15. sqlite-vec con `distance_metric=cosine` esplicito
16. Conversione `similarity = 1 - distance` in range [0, 1]
17. Migrazione automatica DB L2 → cosine

**Round 4 (patch CLI state):**

18. CLI `recall reindex` chiama `set_last_run()` incondizionatamente
19. `recall status` mostra timestamp ISO

### Task 3b-1 (HTTP server stub-equivalent) — 2026-05-17

20. Stack: **FastAPI + uvicorn** (Pydantic già nel progetto)
21. Approccio: **stub-first** (risposte hardcoded bit-equivalent al Node stub)
22. Porta: **8722** (il_segretario), zarsOS è 8721
23. Bind: **127.0.0.1 only**, rifiutato al boot se diverso
24. Auth: **Bearer token** in header, env var configurabile (default `IL_SEGRETARIO_HTTP_TOKEN`)
25. Auth disabilitata se env var vuota (dev mode, WARN al boot)
26. Schema chiuso: `extra="forbid"` Pydantic, blocco chiavi `rawPrivate*`
27. Server: opt-in (`http_server.enabled=false` di default)
28. Spezzettatura Task 3b: 3b-1 (stub) + 3b-2 (logica reale), non 3 sotto-task

---

## 3. Note di design future (parcheggiate)

### 3a. Variante "doppio broker" per privacy a layer multipli
Status: parcheggiata. Non implementata.

### 3b. ~~Wizard di self-discovery~~ → promosso a Task 4

### 3c. Design distribuzione il_segretario + zarsOS
Confermato: **sidecar** (processo Python separato che zarsOS chiama via HTTP locale). Decisione finale (.exe, installer) rimandata a dopo Task 4.

### 3d. FTS5 come secondo retriever (ibrido)
Status: parcheggiato.

### 3e. Salvare chunk content nel DB invece di ri-chunkare a search time
TODO ottimizzazione future.

### 3f. Chunking adattivo per code blocks e tabelle
TODO future.

### 3g. Tokenizzazione vera + retry shrinking per chunks oversize
~10-15% chunks ancora sforano 512 token. Da valutare se la qualità reale soffre.

### 3h. Investigare 3 note "empty response" da Ollama
`Austinitered.md`, `Fluffy_WAR_Bunny.md`, `fapyshop.com.md`. TODO non bloccante.

### 3i. ~~Stack tecnologico server HTTP~~ → deciso FastAPI in Task 3b-1

---

## 4. Bug noti

*(Nessuno. Task 1, Task 2, Task 3b-1 tutti chiusi puliti.)*

---

## 5. Lezioni apprese

### 5a. Sempre smoke test reale prima di commit
Test verdi non garantiscono che il sistema reale funzioni col vault reale. Criteri misurabili dichiarati PRIMA.

### 5b. Verificare parametri dei modelli ML prima di adottarli
mxbai-embed-large: assunto 8192 token, reale 512. Verificare `bert.context_length`.

### 5c. Decisioni di design vengono dall'utente
AI suggerisce con trade-off, utente decide.

### 5d. Onboarding feature opt-in tramite wizard
Default `enabled=false` + wizard di self-discovery al primo trigger.

### 5e. Fix completo richiede di verificare tutti i code path utente
Bug Patch 2 era in CLI + scheduler. Fixato uno solo è bug rimasto. Test riproducono il flusso utente reale.

### 5f. Distinguere modelli embedding da modelli LLM
Gemma/Qwen = generazione. mxbai = embedding. Non intercambiabili.

### 5g. Design ≠ implementazione
Una giornata di design (1219+496 righe per Gateway HTTP) può creare illusione di "feature fatta". Design è ~30% del lavoro.

### 5h. "Chiuso" non basta come parola
"Chiuso su branch" ≠ "mergeato su master". Stato preciso sempre.

---

## 6. Stato repository (snapshot 2026-05-17 sera)

- **master**: contiene Task 1, Task 2, Task 3b-1 (merge commit `891dc33`)
- **Test totali**: 440 verdi
- **Vault reale**: 445 note, 444 indicizzate nel recall
- **zarsOS**: Worker Runner attivo come servizi Windows. Gateway HTTP in implementazione (altra chat).

---

## 7. Tools e versioni

- Python 3.12+
- Node.js >=20 (per zarsOS)
- Ollama locale http://127.0.0.1:11434
- Modelli embedding: `mxbai-embed-large` (in uso)
- Modelli LLM: `gemma4:e4b` (sync), `qwen3.5:9b` (async)
- sqlite-vec, FastAPI, uvicorn
- uv (Python), npm (zarsOS)

---

## 8. Convenzioni di lavoro

- Backup prima di task significativi: `uv run segretario vault backup`
- Worktree git per ogni task
- Smoke test manuale su sistema reale prima di commit
- Note progetto aggiornate dopo ogni task chiuso o decisione importante
- Decisioni numerate (sezione 2)
- Follow-up parcheggiati (sezione 3)
- Bug attivi (sezione 4)
- Lezioni apprese (sezione 5)

---

## 9. Coordinamento tra chat parallele

Chat il_segretario (questa) e chat zarsOS lavorano in parallelo. L'utente fa da ponte.

### Contratto HTTP secretary bridge (il_segretario espone, zarsOS chiama)

Definito e implementato in Task 3b-1:
- Endpoint: `POST /context`, `POST /task`, `GET /health`
- Porta: 8722 (il_segretario)
- Auth: Bearer token dedicato (env var configurabile)
- Schema: closed envelope `secretary_context_request` o `secretary_task_request`
- Blocco chiavi `rawPrivate*` ricorsivo
- Bind: solo `127.0.0.1`

### Contratto HTTP Gateway (zarsOS espone, device chiamano)

Definito in `zarsOS_HTTP_documento_finale.md`. Spec autoritativa, non rediscutere.
- Porta: 8721 (zarsOS)
- Endpoint: `POST /v1/request`, `GET /v1/request/{id}`, ecc.
- Auth: Bearer device-paired
- Done criteria step-by-step in `S1-S9_done_criteria.md`
