# Prompt Claude Code — Task 3b-2 (parte A): logica reale `/context`

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## 1. Contesto

Il server HTTP del Segretario (Task 3b-1) oggi risponde a `POST /context` con
una risposta **finta** hardcoded (`stub_responses.py:build_context_response`).
Questo step la sostituisce con la **logica reale**: cercare davvero nel vault e
restituire una privacy projection (riassunto + vincoli).

Documento autoritativo del contratto col lato zarsOS (l'infrastruttura: gateway,
secretary bridge, validazione — è zarsOS che parla via HTTP col Segretario, non
Zarsuit direttamente): `secretary_bridge_contract.md` (FLUSSO 1 — CONTEXT REQUEST).
I nomi dei campi e i vincoli lì dentro sono **legge**: il bridge zarsOS fa `throw`
se non combaciano.

## 2. Configurazione fissata (decisioni chiuse, non ridiscutere)

- Endpoint, porta (8722), bind `127.0.0.1`, auth Bearer, schema `extra="forbid"`,
  blocco `rawPrivate*`: **già fatti in 3b-1, non si toccano**.
- `/context` resta una projection **piatta** (riassunto + vincoli). NON è la
  correzione dell'attestato di rischio (quello è un flusso separato, fuori scope).
- La projection si fa con i componenti **già esistenti** (`ContextBroker`,
  `RecallEngine.recall_simple`) e con le **regole privacy già nel progetto**
  (`privacy_rules.md` / tassonomia 1–4). Non inventare un nuovo schema di privacy.

## 3. Forma esatta della risposta (da `secretary_bridge_contract.md`, FLUSSO 1 §4-5)

Root: `{ "secretary_context_response": { ... } }`. Campi che il bridge zarsOS legge/valida:

- `request_id` — **echo esatto** di quello in ingresso (mismatch → throw lato zarsOS).
- `status` — SOLO uno di: `allowed`, `partial`, `denied`, `requires_clarification`,
  `handled_by_secretary`. Qualsiasi altro valore → throw.
- `cloud_safe` — deve essere `true` quando `status` è `allowed` o `partial` (altrimenti throw).
- `raw_included` — assente oppure `false`. Se `true` → throw. **Mai dati raw.**
- `context_payload.summary` — stringa (il riassunto sanificato).
- `context_payload.constraints` — array di stringhe (i vincoli d'uso).
- `requires_output_return` — boolean.

L'envelope in ingresso (`secretary_context_request`) contiene tra l'altro:
`request_id`, `user_request_full`, `intent`, `policy_classification`,
`requested_information` (può essere `[]`), `forbidden_context`, `output_policy`.

## 4. Scope

**Entra in questo step:**
- Sostituire `build_context_response` stub con logica reale nell'handler `/context`
  (`app.py` ~:69).
- Parsing tipato dell'envelope `secretary_context_request` (oggi `dict[str,Any]`)
  nei campi che servono (almeno `request_id`, `user_request_full`, `intent`,
  `requested_information`, `forbidden_context`).
- Costruzione del `context_payload` (summary + constraints) reale via
  `ContextBroker` / `RecallEngine.recall_simple` + regole privacy.
- Mappare l'`intent` stringa ricevuto nell'envelope sull'`IntentType` interno.
- Dependency injection nel `create_app`: istanziare/iniettare ciò che serve
  (broker, recall con l'`index_path` reale, eventuale session) — oggi il server è stateless.
- Scrivere un **audit event reale** del Segretario per la gestione del context
  (usa l'`append_event` già esistente).
- Gestione errori: se la projection fallisce (es. Ollama giù/timeout), rispondi
  in modo **sanificato** (nessun raw, nessuno stack trace) con uno status/HTTP
  coerente; **mai** `raw_included: true`.

**NON entra in questo step:**
- `/task` (prossimo prompt).
- L'attestato di rischio via HTTP (rimandato).
- Il percorso di ritorno output (Flow 02): è un `runtime_job`, non un endpoint qui.
- Qualsiasi modifica a porta/auth/bind/schema di 3b-1.

## 5. Vincoli operativi

- Riusa il codice esistente, non riscrivere il `ContextBroker` né il `RecallEngine`.
- Zero nuove dipendenze.
- `recall_simple` resta senza fallback automatico al keyword (decisione Task 2).
- Naming dei campi della response al **millimetro** come §3 (è quello che il bridge zarsOS valida).
- Se trovi ambiguità tra questo prompt e il codice reale (es. da dove arriva il
  `session_id` se serve al broker, o se `compose()` è l'entry giusta o serve una
  funzione più leggera per produrre summary+constraints) → **fermati e segnala**,
  non decidere in autonomia.

## 6. Criteri unit/integration (test verdi obbligatori)

- `/context` con richiesta valida → 200, `status` valido, `request_id` ri-echato,
  `cloud_safe=true`, `raw_included` assente/`false`, `summary` stringa,
  `constraints` lista di stringhe.
- `request_id` ritornato == `request_id` ricevuto.
- Caso `denied` / `partial` gestiti con lo `status` corretto.
- La projection NON contiene path vault raw né contenuto raw (verifica su un caso reale).
- Audit event scritto per la richiesta.
- Errore interno simulato (es. recall non disponibile) → risposta sanificata, niente leak.
- La suite esistente resta verde.

## 7. Criteri smoke reale (su sistema vivo, output nel report)

- Avvia il server e manda una `secretary_context_request` reale con una domanda
  che richiede contesto dal vault; mostra la response JSON completa.
- Una domanda che il vault non copre → `status` coerente (es. `partial`/`denied`).
- Verifica a occhio che `summary`/`constraints` siano sensati e privi di raw.
- Spegni Ollama (o simula) e rifai la richiesta → risposta sanificata, niente crash.

## 8. Reporting a fine step (obbligatorio, verbatim dove indicato)

- File creati/modificati + diff sintetico.
- Output **verbatim** completo di `uv run pytest -q`.
- Output **verbatim** completo degli smoke del §7 (JSON di risposta inclusi).
- Estratto del codice nuovo dell'handler `/context` e del parsing envelope.
- Come hai risolto: mappatura `intent` → `IntentType`; origine del `session_id`
  (se usato); entry usata per produrre summary+constraints; come hai cablato il broker.
- Decisioni implementative minori + razionale.
- Ambiguità incontrate (e dove ti sei fermato).

## 9. Riferimenti

- `secretary_bridge_contract.md` — FLUSSO 1 (CONTEXT), §3 envelope, §4-5 response/validazioni.
- `privacy_rules.md` / `privacy_policy.md` — regole di projection.
- Codice: `app.py` (handler `/context`), `stub_responses.py` (da sostituire),
  `flow02/context_broker.py` (`ContextBroker.compose`), `flow02/recall_engine.py`
  (`recall_simple`), `audit/hash_chain.py` (`append_event`).

## Pre-flight (operatore)

Backup fisico pre-step già fatto prima di lanciare questo prompt. Il developer lo
assume come fatto e non tocca git.
