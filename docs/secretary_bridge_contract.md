# Contratto Bridge zarsOS ↔ Segretario

> Documento di contratto generato da analisi del codice (post-S9, 30/05/2026).
> Fonte di verità: estratto da src/ con riferimenti file:riga. NON modificare
> a mano — rigenerare dall'analisi del codice se il codice cambia.
> Consegna per la sessione che implementa il bridge HTTP lato Segretario.

---

# Report — Bridge e Flussi Segretario (zarsOS)

---

## FLUSSO 1 — CONTEXT REQUEST

### 1. Modulo e funzione di ingresso

**`contextBroker.js:15`** — `ContextBroker.requestContext()`

Chiama (nell'ordine):
1. `secretaryBridge.js:21` → `buildSecretaryContextRequest()` — costruisce l'envelope
2. `secretaryClient.js:21` → `secretaryHttpClient(payload)` — transport HTTP
3. `secretaryBridge.js:64` → `handleSecretaryContextResponse()` — valida e interpreta risposta

### 2. Transport

**HTTP JSON.** — `externalConnections.js:47`:
```
["segretario_context", "secretary_context", "outbound", "http_json", "segretario", "projection_only", true, "secretary_context_request"]
```

### 3. Envelope di richiesta — forma esatta

Root: `{ secretary_context_request: { ... } }`

| Campo | Valore / default | Obbligatorio | Riga |
|-------|-----------------|--------------|------|
| `request_id` | da parametro | **sì** | :32-34 |
| `origin` | `"zarsuit"` (**hardcoded**) | sì | :39 |
| `request_type` | `"context_lookup"` (**hardcoded**) | sì | :40 |
| `user_request_full` | da parametro | **sì** | :32-34 |
| `intent` | da parametro | **sì** | :32-34 |
| `policy_classification` | da parametro | **sì** | :32-34 |
| `reason_for_private_context` | `"Private context may be required to answer safely."` | no | :29 |
| `requested_information` | `[]` | no | :27 |
| `forbidden_context` | `["raw messages","full files","credentials","private paths","vault raw dumps","internal Segretario rules"]` (**hardcoded**) | sì | :46-53 |
| `cloud_visibility` | `"projection_allowed"` | no | :27 |
| `output_return_required` | `false` | no | :27 |
| `risk_notes` | `""` | no | :30 |
| `expected_response_format` | `"structured_context"` (**hardcoded**) | sì | :57 |
| `output_policy` | `"privacy_projection"` (**hardcoded**) | sì | :58 |
| `allow_raw_quotes` | `false` (**hardcoded**) | sì | :59 |

### 4. Envelope di risposta atteso

Root: `{ secretary_context_response: { ... } }`

Campi letti / validati da `secretaryBridge.js:64-121`:

| Campo | Obbligo / vincolo | Causa fail-closed | Riga |
|-------|------------------|-------------------|------|
| `request_id` | obbligatorio | sì | :67 |
| `status` | obbligatorio | sì | :71 |
| `raw_included` | deve essere assente o `false` | **throw se `=== true`** | :72 |
| `cloud_safe` | `=== true` se status allowed/partial | **throw se `!== true`** | :77-79 |
| `context_payload.summary` | string | — | :170-173 |
| `context_payload.constraints` | array of string | — | :173-177 |
| `requires_output_return` | boolean | — | :86 |

Valori `status` e loro effetti:

| `status` | `state` ritornato | `zarsuitMustStop` |
|----------|------------------|-------------------|
| `"allowed"` | `"context_allowed"` | `false` |
| `"partial"` | `"context_partial"` | `false` |
| `"denied"` | `"context_denied"` | `false` |
| `"requires_clarification"` | `"requires_clarification"` | `false` |
| `"handled_by_secretary"` | `"handled_by_secretary"` | **`true`** |
| qualsiasi altro | — | **throw** (riga :119) |

### 5. Validazioni e invarianti

- `secretaryBridge.js:72` — `raw_included === true` → throw `"raw secretary context is forbidden"`
- `secretaryBridge.js:77-79` — status allowed/partial + `cloud_safe !== true` → throw `"context projection must be cloud_safe"`
- `secretaryBridge.js:68-70` — `request_id` mismatch con atteso → throw `"secretary context request_id mismatch"`
- `contextBroker.js:39-49` — qualsiasi eccezione → audit `"failed_closed"` + ritorno `{ state: "failed_closed", zarsuitMustStop: false }`

### 6. Audit event

`contextBroker.js:52-64`:
```json
{
  "request_id": "<requestId>",
  "actor": "zarsuit",
  "event": "secretary_context_request",
  "policy_decision": "delegate_to_secretary" | "deny",
  "capability_requested": "vault.context_request",
  "capability_decision": "delegate_to_secretary" | "deny",
  "confirmation_required": false,
  "tool_wrapper": "secretary_context_bridge",
  "result": "<parsed.state>" | "failed_closed"
}
```

---

## FLUSSO 2 — TASK REQUEST

### 1. Modulo e funzione di ingresso

**`secretaryTaskBroker.js:11`** — `SecretaryTaskBroker.requestTask()`

Chiama:
1. `secretaryBridge.js:181` → `buildSecretaryTaskRequest()` — costruisce envelope
2. `secretaryClient.js:21` → `secretaryHttpClient(payload)` — transport HTTP
3. `secretaryBridge.js:123` → `handleSecretaryTaskResult()` → `deliverSecretaryFinalResponse()` — valida e restituisce contenuto

### 2. Transport

**HTTP JSON.** — `externalConnections.js:48`:
```
["segretario_task", "secretary_task", "outbound", "http_json", "segretario", "secretary_owned", true, "secretary_task_request"]
```

### 3. Envelope di richiesta — forma esatta

Root: `{ secretary_task_request: { ... } }`

```
secretary_task_request
├── version: "1.0"                                        [hardcoded :191]
├── request
│   ├── request_id: "str_<uuid>"                          [generato :192]
│   ├── created_at: "<ISO timestamp>"                     [generato :193]
│   ├── source_agent: "zarsuit"                           [hardcoded :194]
│   └── target_agent: "segretario"                        [hardcoded :195]
├── user_request
│   ├── original_input: <userInput>
│   ├── interpreted_intent: <intent.interpretedIntent>
│   └── user_visible_goal: <intent.userVisibleGoal>
├── task
│   ├── domain: intent.domain ?? "mixed"
│   ├── action_type: intent.actionType ?? "draft"
│   ├── action_name: intent.actionName
│   └── priority: intent.priority ?? "normal"
├── handoff
│   ├── mode: "full_secretary_execution"                  [hardcoded :209]
│   ├── zarsuit_may_process_result: false                 [hardcoded :210]
│   ├── zarsuit_may_edit_final_output: false              [hardcoded :211]
│   ├── secretary_owns_final_output: true                 [hardcoded :212]
│   └── delivery_mode: "secretary_final_response"         [hardcoded :213]
├── privacy
│   ├── expected_sensitivity: SENSITIVITY_BY_DOMAIN[domain] ?? "high"
│   ├── private_data_needed: inferPrivateDataNeeded(domain) [tabella :269-287]
│   ├── expose_raw_data_to_zarsuit: false                 [hardcoded :218]
│   └── allowed_output_level: "secretary_final_response"  [hardcoded :219]
├── execution_policy
│   ├── may_execute_without_user_confirmation: <calcolato>
│   ├── requires_user_confirmation_before_final_action: <calcolato>
│   ├── allow_secretary_to_refuse: true                   [hardcoded :225]
│   └── allow_secretary_to_ask_clarification: true        [hardcoded :226]
├── constraints
│   ├── time_range: null                                  [hardcoded :229]
│   ├── people_involved: []                               [hardcoded :230]
│   └── forbidden_actions: [                              [hardcoded :231-234]
│       "send_without_confirmation",
│       "expose_raw_private_data_to_zarsuit",
│       "zarsuit_final_output_rewrite"
│   ]
├── desired_result
│   ├── format: "secretary_final_response"                [hardcoded :237]
│   ├── include_private_details_for_zarsuit: false        [hardcoded :238]
│   └── secretary_prepares_user_output: true              [hardcoded :239]
└── audit
    ├── write_to_vault_audit: true                        [hardcoded :242]
    ├── store_request_copy: true                          [hardcoded :243]
    └── store_result_copy: true                           [hardcoded :244]
```

### 4. Envelope di risposta atteso

Root: `{ secretary_task_result: { ... } }`

Validazioni in `handleSecretaryTaskResult()` + `deliverSecretaryFinalResponse()`:

| Campo | Vincolo | Causa fail | Riga |
|-------|---------|-----------|------|
| `request.request_id` | string non-vuota | **throw** | :126-127 |
| `privacy.raw_private_data_exposed_to_zarsuit` | deve essere `false` | **throw** se `=== true` | :132-134 |
| `privacy.output_sanitized_by_secretary` | deve essere `true` | **throw** se `!== true` | :135-137 |
| `audit.stored` | deve essere `true` | **throw** se `!== true` | :138-140 |
| `status.state` | uno di: completed, refused, requires_confirmation, requires_clarification, failed | **throw** altrimenti | :142-144 |
| `ownership.output_owner` | deve essere `"segretario"` | **throw** | :257 |
| `ownership.zarsuit_processing_allowed` | deve essere `false` | **throw** | :258 |
| `ownership.zarsuit_editing_allowed` | deve essere `false` | **throw** | :259 |
| `final_response.audience` | deve essere `"user"` | **throw** | :260 |
| `final_response.content` | string obbligatoria | **throw** | :261 |
| `final_response.content` (dopo outputGuard) | redactions.length deve essere `0` | **throw** se > 0 | :263-265 |

Invariante confirmation (`secretaryBridge.js:157-165`):
- `status.state === "requires_confirmation"` richiede `confirmation.required === true`
- qualsiasi altro stato con `confirmation.required === true` → **throw** `"incoherent"`

### 5. Validazioni e invarianti

- `secretaryBridge.js:263-265` — se `guardUserOutput(content).redactions.length > 0` → throw `"secretary final response cannot be delivered unchanged"` — il content della risposta finale NON può contenere segreti/schemi interni, altrimenti viene bloccata
- `secretaryTaskBroker.js:20-29` — qualsiasi eccezione → audit `"failed_closed"` + `{ zarsuitMayAnswerUser: false }`

### 6. Audit event

`secretaryTaskBroker.js:33-45`:
```json
{
  "request_id": "<request.requestId>",
  "actor": "zarsuit",
  "event": "secretary_task_request",
  "policy_decision": "delegate_to_secretary",
  "capability_requested": "secretary.task_request",
  "capability_decision": "delegate_to_secretary" | "deny",
  "confirmation_required": "<taskState> === 'requires_confirmation'",
  "tool_wrapper": "secretary_task_bridge",
  "result": "<taskState>" | "failed_closed"
}
```

---

## FLUSSO 3 — RISK ATTESTATION

### 1. Modulo e funzione di ingresso

**`riskFlow.js:23`** — `RiskAttestationExchange.processUserRequest()`

Chiama:
1. `riskAttestation.js:14` → `buildInitialAttestation()` — costruisce attestazione draft
2. `riskFlow.js:41` → `this.secretaryReviewer(initialAttestation)` — invia al revisore
3. `riskAttestation.js:77` → `validateAttestation()` — valida risposta
4. `riskAttestation.js:99` → `enforceFlow02Routing()` — determina routing
5. Se `outputDestination === "secretary"` → `flow02.js:8` → `Flow02SecretaryReturn.process()`
6. Altrimenti → `riskAttestation.js:138` → `buildZarsuitExecutionInput()` → `this.reasoner()`

### 2. Transport

**CALLBACK** — NON HTTP. `externalConnections.js:50-51`:
```
["risk_reviewer", "risk_reviewer", "outbound", "callback", "segretario", "projection_only", true, "risk_attestation_exchange"]
["risk_reasoner", "risk_reasoner", "outbound", "callback", "zarsuit", "public_or_projection_only", true, "risk_attestation_exchange"]
```

`secretaryReviewer` è iniettato nel costruttore (`riskFlow.js:14`) come funzione callable. **Non usa `secretaryClient.js`.** Il punto esatto dove andrebbe un adapter HTTP è `riskFlow.js:41`:
```js
const correctedAttestation = await this.secretaryReviewer(initialAttestation);
```
— sostituire `this.secretaryReviewer` con un wrapper che chiama `secretaryClient` con l'envelope `risk_attestation`.

### 3. Envelope di richiesta — forma esatta

Root: `{ risk_attestation: { ... } }` — da `riskAttestation.js:23-74`:

```
risk_attestation
├── schema_version: "1.0"                                 [hardcoded :25]
├── attestation_id: "risk_<uuid>"                         [generato :26]
├── created_at: "<ISO timestamp>"                         [generato :27]
├── created_by: "zarsuit"                                 [hardcoded :28]
├── status: "draft"                                       [hardcoded :29]
├── original_user_request
│   ├── full_text: <fullText>                             [obbligatorio]
│   ├── detected_intent: <detectedIntent>
│   └── user_expected_output: <expectedOutput>
├── zarsuit_context_request
│   ├── requested_private_data: []                        [default]
│   └── requested_vault_knowledge: []                     [default]
├── zarsuit_initial_risk_assessment
│   ├── level: "high"                                     [default :20]
│   ├── rationale: "Request may require private profile, vault, or operational context."  [hardcoded :41]
│   ├── risks: ["personal_data_exposure","profile_inference","unverified_output"]         [default :21]
│   └── notes: "Full user request included for secretary review."  [hardcoded :43]
├── secretary_review                                      [compilato dal Segretario]
│   ├── corrected_risk_level: <riskLevel>
│   ├── corrected_notes: ""
│   ├── approved_context_projection: []
│   └── denied_context: []
├── secretary_routing_directive                           [FAIL-CLOSED di default]
│   ├── zarsuit_may_answer_user_directly: false           [hardcoded :52]
│   ├── zarsuit_must_return_output_to_secretary: false    [hardcoded :53]
│   ├── user_delivery_blocked_until_secretary_approval: false [hardcoded :54]
│   ├── task_output_destination: "secretary"              [hardcoded :55]
│   └── reason: "Fail-closed until il_segretario corrects routing."  [hardcoded :56]
├── zarsuit_execution
│   ├── allowed_to_execute: false                        [hardcoded :59 — fail-closed]
│   ├── allowed_inputs_only: "secretary_approved_context_projection" [hardcoded :60]
│   └── execution_notes: ""
├── zarsuit_task_output_for_secretary
│   ├── status: "not_required"                           [hardcoded :64]
│   └── content: ""
└── audit
    ├── secretary_keeps_vault_copy: true                 [hardcoded :68]
    ├── corrected_copy_returned_to_zarsuit: true         [hardcoded :69]
    └── final_user_delivery_out_of_scope_for_this_contract: true [hardcoded :70]
```

### 4. Envelope di risposta atteso (correctedAttestation)

Stessa struttura `risk_attestation` ritornata dal `secretaryReviewer` con i campi corretti.

Validazioni obbligatorie in `validateAttestation()` — `riskAttestation.js:77-97`:

| Campo | Riga |
|-------|------|
| `risk_attestation` root presente | :79 |
| `schema_version` | :81 |
| `attestation_id` | :82 |
| `created_at` | :83 |
| `created_by` | :84 |
| `original_user_request.full_text` | :85 |
| `zarsuit_context_request` | :86 |
| `zarsuit_initial_risk_assessment.level` | :87 |
| `secretary_review` | :88 |
| `secretary_routing_directive` | :89 |
| `routing.zarsuit_may_answer_user_directly` (boolean, required) | :90 |
| `routing.zarsuit_must_return_output_to_secretary` (boolean, required) | :91 |
| `routing.task_output_destination` | :92 |
| `zarsuit_execution.allowed_inputs_only` | :93 |
| `audit.final_user_delivery_out_of_scope_for_this_contract` (boolean, required) | :94 |

### 5. Validazioni e invarianti — `enforceFlow02Routing()`

`riskAttestation.js:99-136`:

| Condizione | Throw / effetto |
|-----------|----------------|
| `task_output_destination` non in `["user","secretary"]` | throw `"unsupported routing destination"` |
| `user_delivery_blocked === true` + `zarsuit_may_answer_user_directly !== false` | throw `"Blocked user delivery requires..."` |
| `zarsuit_may_answer_user_directly === true` + `zarsuit_must_return_to_secretary === true` | throw `"Routing cannot both..."` |
| Flow02: `zarsuit_must_return_to_secretary === true` + `zarsuit_may_answer_user_directly !== false` | throw `"Flow 02 requires zarsuit_may_answer_user_directly=false"` |
| Flow02: `zarsuit_must_return_to_secretary === true` + `destination !== "secretary"` | throw `"Flow 02 requires task_output_destination=secretary"` |
| Flow02: `zarsuit_must_return_to_secretary === true` + `user_delivery_blocked !== true` | throw `"Flow 02 requires user delivery blocked..."` |

In `buildZarsuitExecutionInput()` — `riskAttestation.js:141-143`:
- `allowed_inputs_only !== "secretary_approved_context_projection"` → throw

### 6. Audit event

`riskFlow.js:87-99`:
```json
{
  "request_id": "<attestation_id>",
  "actor": "zarsuit",
  "event": "risk_attestation_exchange",
  "policy_decision": "allow" | "deny",
  "capability_requested": "secretary.risk_attestation_review",
  "capability_decision": "allow" | "deny",
  "confirmation_required": false,
  "tool_wrapper": "risk_attestation_exchange",
  "result": "completed" | "returned_to_secretary" | "failed_closed"
}
```

Flow02 emette un audit separato — `flow02.js:57-68`:
```json
{
  "actor": "zarsuit",
  "event": "flow_02_secretary_return",
  "capability_requested": "secretary.return_output",
  "capability_decision": "delegate_to_secretary",
  "tool_wrapper": "flow_02_secretary_return",
  "result": "returned_to_secretary" | "failed_closed"
}
```

---

## DOMANDE TRASVERSALI

### Q1 — Quanti endpoint HTTP distinti? Come si distingue context da task?

**Due endpoint distinti**, oppure uno condiviso — configurazione mutuamente esclusiva.

Da `secretaryConfig.js:107-112`:
- Se `endpoint` è impostato, `context_endpoint` e `task_endpoint` **devono essere null** (altrimenti: throw `"ambiguous"`)
- Se `context_endpoint` o `task_endpoint` è impostato, `endpoint` **deve essere null** e **entrambi devono essere impostati** (altrimenti: throw `"incomplete"`)

La risoluzione dell'endpoint effettivo avviene in `effectiveEndpoint()` — `secretaryConfig.js:160-164`:
```js
kind === "context" → context_endpoint ?? endpoint
kind === "task"    → task_endpoint ?? endpoint
```

La distinzione context/task avviene a **tre livelli sovrapposti**:
1. **URL** — endpoint fisicamente diversi (se configurati separatamente)
2. **Header HTTP** — `x-zarsos-client: "secretary-context"` vs `"secretary-task"` (`secretaryClient.js:39`, `clientHeaderForPayloadKind()` :96-98)
3. **Root payload JSON** — chiave unica `secretary_context_request` vs `secretary_task_request` (`secretaryClient.js:79`)

### Q2 — Il flusso risk_attestation usa lo stesso transport di context/task?

**No. Transport diverso.**

| Flusso | Transport | Dichiarato in externalConnections |
|--------|-----------|----------------------------------|
| context | `http_json` | riga :47 |
| task | `http_json` | riga :48 |
| risk_attestation (reviewer) | `callback` | riga :50 |
| risk_attestation (reasoner) | `callback` | riga :51 |

**Punto esatto per un adapter HTTP** — `riskFlow.js:41`:
```js
const correctedAttestation = await this.secretaryReviewer(initialAttestation);
```
L'envelope da inviare via HTTP sarebbe la struttura `risk_attestation` costruita da `buildInitialAttestation()`. Il client potrebbe riusare `createSecretaryHttpClient` con un terzo endpoint e un terzo root `"secretary_risk_review_request"` (o equivalente — **non definito nel codice attuale**).

### Q3 — Il Flow02 è una chiamata HTTP separata o un flag?

**Né l'una né l'altro — è un return strutturato in memoria.**

`Flow02SecretaryReturn.process()` (`flow02.js:29`) chiama `packageOutputForSecretary()` che costruisce:
```json
{
  "zarsuit_task_output_for_secretary": {
    "source_attestation_id": "...",
    "status": "completed",
    "destination": "secretary",
    "user_delivery_allowed": false,
    "content": "<generatedOutput>"
  }
}
```
Questo viene restituito a `riskFlow.js` come `{ state: "returned_to_secretary", outputForSecretary }` — **nessuna chiamata HTTP viene eseguita**. L'output resta nell'oggetto di ritorno dell'orchestratore.

`externalConnections.js:49` classifica `segretario_return` come `transport: "runtime_job"` — il design prevede che il Segretario recuperi l'output tramite job store, non che Zarsuit lo invii attivamente via HTTP.

**Da dove parte:** `riskFlow.js:45-51` — se `routing.outputDestination === "secretary"` → `flow02.process()`
**Dove viene gestito:** `flow02.js:29` → `packageOutputForSecretary()` → ritorno all'orchestratore

### Q4 — Quali chiavi/pattern blocca outputGuard per schemi interni Segretario?

`outputGuard.js:31-35` — quattro pattern distinti, applicati in sequenza (righe :102-106):

| Pattern | Cosa blocca | Sostituzione | Riga applicazione |
|---------|------------|--------------|-------------------|
| `INTERNAL_SCHEMA_JSON_PATTERN` | JSON contenenti: `secretary_task_request`, `secretary_context_request`, `risk_attestation`, `zarsuit_task_output_for_secretary`, `zarsuit_execution_input`, `secretary_routing_directive`, `tool_call`, `function_call`, `internal_tool`, `arguments` | `[INTERNAL_SCHEMA_REDACTED]` | :102 |
| `TOOL_JSON_PATTERN` | JSON piatti contenenti: `tool_call`, `function_call`, `arguments`, `internal_tool` | `[INTERNAL_TOOL_JSON_REDACTED]` | :103 |
| `INTERNAL_SCHEMA_TAG_PATTERN` | Tag XML: `<system>`, `<developer>`, `<internal_schema>`, `<zarsuit_internal_schema>`, `<tool_schema>`, `<function_schema>` | `[INTERNAL_SCHEMA_REDACTED]` | :104 |
| `INTERNAL_SCHEMA_LINE_PATTERN` | Righe inizianti con: `role: system/developer`, `zarsuit_internal_schema:`, `schema_internal:`, `internal_schema:`, `tool_schema:`, `function_schema:`, `recipient: functions.*` | `[INTERNAL_SCHEMA_REDACTED]` | :105 |

`INTERNAL_SCHEMA_KEY_PATTERN` (**riga :35**) — definisce le stesse keyword degli schemi, ma **non è applicato in `guardUserOutput()`**. È usato **solo** in `sanitizePersistenceKey()` (`outputGuard.js:173`) per sanitizzare le **chiavi** degli oggetti JSON prima della persistenza su disco.

### Q5 — Divergenze tra i tre envelope

| Dimensione | Context request | Task request | Risk attestation |
|-----------|----------------|-------------|-----------------|
| **Root key** | `secretary_context_request` | `secretary_task_request` | `risk_attestation` |
| **Versioning** | assente | `version: "1.0"` | `schema_version: "1.0"` — nome campo diverso |
| **Struttura** | piatta (1 livello) | gerarchica (4 livelli: request/task/handoff/privacy/…) | profonda (5+ livelli) |
| **request_id** | campo diretto `request_id` | annidato in `request.request_id` | in `attestation_id` (nome diverso) |
| **Naming rispondente** | `secretary_context_response` | `secretary_task_result` — **suffisso diverso** (`response` vs `result`) | stessa struttura `risk_attestation` ritornata — non c'è root response distinto |
| **request_id nella risposta** | `secretary_context_response.request_id` | `secretary_task_result.request.request_id` — **annidato** | `risk_attestation.attestation_id` — nome campo diverso |
| **Transport** | HTTP JSON | HTTP JSON | callback |
| **Audit field "event"** | `"secretary_context_request"` | `"secretary_task_request"` | `"risk_attestation_exchange"` |
