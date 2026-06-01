# Task 3b-2b — Logica reale per `POST /task` (il_segretario)

> Prompt di implementazione per Claude Code. Repo: `E:\il_segretario`.
> Sostituisce la risposta hardcoded dello stub `/task` con logica reale.
> `/context` (3b-2a) è già implementato: **specchia la struttura di
> `http_server/context_handler.py`**, non reinventarla.

---

## 0. Hard rules (non negoziabili)

1. **Piccolo e corretto, non ampio e speculativo.** Non inventare decisioni
   non presenti in questo prompt. Se un requisito è ambiguo → **fermati e chiedi**.
2. La forma della risposta `secretary_task_result` è fissata dal contratto
   (`docs/secretary_bridge_contract.md`). Se qualcosa qui diverge dal contratto,
   **vince il contratto** → fermati e segnala.
3. Convenzioni di progetto: worktree git dedicato; backup vault prima
   (`uv run segretario vault backup`); **smoke test reale prima del commit**;
   nessun commit finché lo smoke non passa.
4. Baseline: esegui `uv run pytest -q` **prima di iniziare** e registra il
   conteggio verde di partenza. Non deve regredire. (Il numero varia tra le
   chat parallele — non assumerlo, misuralo.)

---

## 1. Scope di 3b-2b

`/task` fa **classificazione + preparazione della risposta + gating della
conferma**. **NESSUNA esecuzione side-effecting reale** (niente invio email,
niente scrittura vault, niente azioni su Gmail/Calendar). L'esecuzione vera
dipende dal Taskboard/endpoint di conferma (GAP #6) e vive in un task futuro.

`requires_confirmation` significa quindi: *"bozza pronta, azione NON eseguita"*.

---

## 2. Contratto di risposta — invarianti fissati (da `secretary_bridge_contract.md`)

La risposta è `{ "secretary_task_result": { ... } }`. Questi vincoli valgono
per **OGNI** stato, altrimenti il lato Zarsuit lancia:

- `request.request_id` = echo di `secretary_task_request.request.request_id`
  (usa `validate_safe_request_id`).
- `ownership.output_owner = "segretario"`, `zarsuit_processing_allowed = false`,
  `zarsuit_editing_allowed = false`.
- `final_response.audience = "user"`.
- `final_response.content` = **stringa non vuota, SEMPRE** (anche refused/failed),
  e deve passare il guard formato-Node con **zero redazioni**.
- `privacy.raw_private_data_exposed_to_zarsuit = false`,
  `privacy.output_sanitized_by_secretary = true`.
- `audit.stored = true` **solo dopo** che un `append_event` reale è andato a buon fine.
- `status.state` ∈ `{completed, requires_confirmation, refused, failed}`.
  `requires_clarification` è **rimandato** (nessun detector di ambiguità ora).
- `confirmation.required = true` **se e solo se** `state == requires_confirmation`;
  `false` per tutti gli altri stati (il lato Node lancia se uno stato ≠
  requires_confirmation ha `required == true`). **Droppa `pending_action`**:
  Zarsuit legge solo `confirmation.required`.

---

## 3. Logica di decisione (il nuovo core)

### 3.1 Parsing della request
Estrai da `secretary_task_request`:
- `request.request_id`
- `task.domain`, `task.action_type`, `task.action_name`
- `privacy.private_data_needed`
- `execution_policy.*` → **solo informativo**. Il Segretario NON si fida:
  ri-deriva la decisione col proprio `PermissionKernel`.

### 3.2 Mapping azione → costante kernel
Crea una tabella di mapping **esplicita e nuova** da
`(domain, action_type, action_name)` alle costanti di `policies/permissions.py`
(es. `GMAIL_SEND`, `CALENDAR_CREATE`, `KNOWLEDGE_WRITE`, ...).
**Conservativo: azione non mappata → trattata come DENY** (fail-closed).
Se l'azione è ambigua, **non indovinare**: DENY + annota per review.

### 3.3 `PermissionKernel.decision_for(action)` → stato
- `ALLOW`   → `state = completed`        → genera content (risposta/risultato preparato)
- `CONFIRM` → `state = requires_confirmation` → genera content (descrive l'azione
  preparata + "serve conferma"); `confirmation.required = true`; **nessuna esecuzione**
- `DENY`    → `state = refused`          → content = rifiuto cortese
- **qualsiasi altro esito (incl. `PROJECT`)** → `state = refused`,
  reason interna `unsupported_decision_for_task` (default difensivo, niente
  match non esaustivo)

### 3.4 Path di errore
Su eccezione interna / `LocalModelUnavailable` / guard che scatta (vedi §5):
- `state = failed`
- content = **messaggio di fallimento templato** (NIENTE LLM sulla path d'errore)
- emetti comunque l'envelope completo (ownership/privacy corretti) e l'audit

---

## 4. Generazione del content (modello sync) — specchia `/context`

- Usa il `llm_client` (`OllamaClient`) iniettato nella factory, stesso pattern
  di `_synthesize_with_gemma` in `context_handler.py`.
- **Non hardcodare il nome del modello.** Usa sempre `settings.llm.sync_model`.
  `/task` eredita qualunque modello sia configurato — niente riferimenti
  letterali a un modello specifico, nel codice e nei test.
- **System prompt** = `CharacterStore.identity()` (voce/persona) + una riga di
  framing del task. **ZERO divieti privacy nel prompt** — l'enforcement è
  strutturale (guard + projection), non prompt-based. I divieti in-prompt
  innescano e sono inaffidabili.
- Wira `CharacterStore` nella factory/handler HTTP (oggi è usato solo dal CLI).
  `CharacterStore.from_config(settings.character.identity)`.
- **`keep_alive` sul modello sync**: aggiungi config `llm.sync_model_keep_alive`
  (default `-1` = sempre residente, implementa l'intento "modello sync sempre caldo").
  Passalo nel body della request `/api/generate` di `OllamaClient`.
  **Commento nel codice**: quando arriverà il consolidamento async / model-swap
  (Fase 5), `keep_alive` dovrà coordinarsi con un unload-before-consolidate per
  non contendere la VRAM (16 GB) col modello pesante.

---

## 5. Guard formato-Node (NUOVO — GAP #7)

Nuova funzione in `policies/output_guard.py`, es.
`guard_zarsuit_schema_leak(content) -> GuardResult` (con lista `redactions`).
Specchia **semanticamente** (non copia-incolla di regex JS) i **4 pattern** della
tabella Q4 di `secretary_bridge_contract.md` — che è la **fonte unica** di verità:

1. JSON con chiavi: `secretary_task_request`, `secretary_context_request`,
   `risk_attestation`, `zarsuit_task_output_for_secretary`,
   `zarsuit_execution_input`, `secretary_routing_directive`, `tool_call`,
   `function_call`, `internal_tool`, `arguments`
2. JSON piatto con `tool_call` / `function_call` / `arguments` / `internal_tool`
3. Tag XML: `<system>`, `<developer>`, `<internal_schema>`,
   `<zarsuit_internal_schema>`, `<tool_schema>`, `<function_schema>`
4. Righe che iniziano con `role: system|developer`, `zarsuit_internal_schema:`,
   `schema_internal:`, `internal_schema:`, `tool_schema:`, `function_schema:`,
   `recipient: functions.*`

**Coordinamento coi guard esistenti (non duplicare):**
- Ordine: il modello sync genera → `guard_zarsuit_schema_leak` → se scatta (`redactions > 0`)
  **fail-closed** (`state = failed`, content templato, audit del flag); **NON**
  emettere testo redatto/rabberciato → poi `sanitize_user_output` esistente
  (OAuth/path) sul content finale, come già fa la pipeline di `/context`.
- `_has_raw_private_key` resta sull'input (Pydantic), non c'entra con l'output.

**Anti-drift:** test che asserisce che il guard becca esattamente i pattern
della tabella Q4 (pin alla lista del contratto), così la divergenza da zarsOS
emerge in CI.

---

## 6. Audit (GAP #4)

- Prima di settare `audit.stored = true`, chiama
  `audit_log.append_event("secretary_task_request", {...})`.
- **Decision audit fields** (richiesti dal threat model): `request_id`,
  `action` (mappata), `kernel_decision` (ALLOW/CONFIRM/DENY/...), `result_state`,
  `output_sanitized` (bool), `guard_fired` (bool).
- **Naming caveat**: l'audit redige da sé qualsiasi chiave la cui forma
  normalizzata contenga `content`/`text`/`raw`/`body`/`auth`/`token`/`secret`/...
  (`hash_chain.SENSITIVE_KEYS`). Nomina i campi per **non** farti redarre un
  campo che vuoi tenere, e tieni i valori a **soli metadati di decisione**
  (niente testo libero / dati utente).
- `audit.stored = true` **solo se** `append_event` è riuscito; se la scrittura
  audit fallisce → `state = failed` (non puoi attestare `stored`).

---

## 7. Modello di risposta (GAP #10) — DECISO

Mantieni il pattern di response a **dict Python serializzato via `JSONResponse`**,
identico a `stub_responses.py` di Task 3b-1. **Non introdurre Pydantic response
models.** La struttura del dict `secretary_task_result` resta **invariata**;
cambiano solo i **valori**, che ora derivano da `PermissionKernel` (per
`status.state` e `confirmation.required`) e dal modello sync (`final_response.content`)
invece di essere hardcoded.

Motivi (decisione confermata dalla chat che ha originato la task):
1. Coerenza col codice già in master di 3b-1 e con `/context` (3b-2a).
2. Lo schema di risposta è **imposto dal contratto zarsOS**: `secretaryClient.js`
   fa `JSON.parse` e si aspetta `secretary_task_result` come root. Un response
   model Pydantic aggiungerebbe un layer che non protegge da nulla in più — il
   consumatore è Zarsuit, non noi.
3. La validazione che conta è già coperta: `extra="forbid"` + `_has_raw_private_key`
   sull'**input** (Pydantic request), e il guard formato-Node (§5) sull'**output**.

---

## 8. Struttura file attesa

- `http_server/task_handler.py` — nuovo, analogo a `context_handler.py`
  (parsing, mapping, decisione, generazione, guard, audit, build risposta).
- `app.py` — l'handler `/task` chiama `build_task_response_real(...)` del nuovo
  modulo invece dello stub; inietta `recall_engine`/`audit_log`/`llm_client`
  (+ `character_store`) come già fa `/context`.
- `policies/output_guard.py` — aggiungi `guard_zarsuit_schema_leak`.
- `settings.py` — aggiungi `llm.sync_model_keep_alive` (default `-1`).
- `policies/permissions.py` — usa l'esistente; aggiungi solo la tabella di
  mapping azione→costante (dove ha senso: handler o un piccolo modulo dedicato).
- Lo stub `stub_responses.build_task_response` può restare per riferimento o
  essere rimosso; non deve più essere chiamato da `/task`.

---

## 9. Test (GAP #8) — estendi `tests/test_http_server.py`

Riusa `fake_audit` e il pattern `_make_app_with_recall`; crea
`_make_app_for_task()` analogo. **Nessun Ollama reale nei test** (`_FakeLLMClient`).

- Riscrivi `test_task_happy_path`: tieni le asserzioni sulla **forma**, cambia le
  attese sui **valori** (comportamento reale).
- Decisione: `ALLOW → completed`, `CONFIRM → requires_confirmation`,
  `DENY → refused`, `PROJECT/sconosciuto → refused` (difensivo).
- Coerenza confirmation: `required` true solo su `requires_confirmation`,
  false altrove.
- Audit: `append_event` chiamato; `audit.stored = true` solo dopo; fallimento
  audit → `failed`.
- Guard formato-Node: content con finto `<system>` / `tool_call` / JSON con
  `secretary_task_request` → `failed`, content templato, **non** rabberciato/leakato.
- Copertura pattern guard pinnata alla lista Q4 del contratto (anti-drift).
- `final_response.content` sempre stringa non vuota per **ogni** stato.
- `LocalModelUnavailable` → `failed` con content templato.

---

## 10. Condizioni di stop (fermati e chiedi)

1. Un `(domain, action_type)` non è nella tabella di mapping → DENY (non
   indovinare) + annota.
2. Wirare `CharacterStore` nella factory confligge con la firma esistente.
3. Qualcosa diverge da `secretary_bridge_contract.md` → vince il contratto.

---

## 11. Acceptance

- `uv run pytest -q` verde (baseline di partenza + nuovi test).
- **Smoke reale**: avvia il server, `POST` un `secretary_task_request` campione
  per ciascuna classe di decisione; verifica forma + `status.state` del
  `secretary_task_result`; verifica che `state/audit/events.jsonl` abbia ricevuto
  gli eventi; verifica che un content forgiato con `<system>`/`tool_call` produca
  `failed` senza leak.
- Backup vault fatto; branch worktree; nessun commit prima dello smoke verde.
