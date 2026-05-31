# il_segretario — Flow 02: Protocollo Zarsuit

> **Fonte decisioni:** `docs/secretary-flow02-decisions.md` e `docs/zarsOS_multi_device_design.md`.
> **Template strutturale:** `docs/IL_SEGRETARIO_CODEX_SPEC.md`.
> **Scope:** definire e implementare il protocollo con cui Zarsuit invoca il_segretario
> come hub locale, inclusi contratti, composizione del contesto a 3 livelli,
> Risk Attestation Exchange, retry loop, gestione sessione e integrazione
> modello asincrono.
>
> **Hard rule:** non inventare decisioni non presenti nei documenti fonte.
> Se un requisito è ambiguo, fermarsi e chiedere.
> Preferire un'implementazione piccola e corretta a una ampia e speculativa.

---

## 0. Decisioni non negoziabili

1. il_segretario è **l'hub** di zarsOS. Zarsuit lo invoca — non il contrario (salvo il retry loop, vedi §4).
2. Zarsuit non esiste ancora. Ogni punto di contatto con Zarsuit usa una **stub interface** (ZarsuitClient astratto + implementazione mock).
3. I modelli LLM sono due: **sincrono** (Gemma 4 9B, sempre caldo) per i turni utente; **asincrono** (Qwen3.5 9B o 27B, caricato on-demand) per il consolidamento di fine sessione.
4. La **privacy non limita il volume** del contesto inviato a Zarsuit: i dati escono già tokenizzati e generalizzati dalla privacy projection. Il limite è solo performance (latenza e qualità del ragionamento).
5. Il Segretario verifica **forma e contratto**, non correttezza fattuale dell'output di Zarsuit.
6. §8.1 (prompt injection detection) e §8.2 (recall livello 3) sono **esplicitamente fuori scope** di questo spec. Verranno trattati in spec dedicati.
7. Il transport layer definitivo (HTTP/API) è fuori scope. Per ora il protocollo è esposto via CLI. Sarà sostituito quando Zarsuit sarà costruito.

---

## 1. Definizione del prodotto

Flow 02 è il **protocollo operativo** attraverso cui Zarsuit utilizza il_segretario come hub locale.

Il_segretario, in questo protocollo:

- riceve richieste di contesto da Zarsuit;
- compone un pacchetto a 3 livelli (identità statica + working memory sanificata + recall on-demand);
- emette e verifica il **Risk Attestation Exchange** — il contratto che Zarsuit firma prima di ricevere contesto;
- valida l'output di Zarsuit contro il contratto firmato;
- esegue fino a 2 retry se l'output non è conforme;
- gestisce il ciclo di vita delle sessioni (apertura, log JSONL, chiusura con doppia condizione, consolidamento asincrono).

---

## 2. Architettura di alto livello

```text
Client (utente)
  │
  ▼
Gateway  ──────────────────────────────────────────┐
  │                                                 │
  ▼                                                 │
ZarsuitAgent (Claude-backed, stub per ora)          │
  │                                                 │
  │  SecretaryContextRequest / SecretaryTaskRequest │
  ▼                                                 │
il_segretario Hub                                   │
  │                                                 │
  ├── ContextBroker                                 │
  │     ├── L1: CharacterStore (identità statica)   │
  │     ├── L2: WorkingMemory (turni sanificati)    │
  │     └── L3: RecallEngine (on-demand, stub)      │
  │                                                 │
  ├── RiskAttestationExchange                       │
  │     ├── AttestationBuilder                      │
  │     └── ContractVerifier                        │
  │                                                 │
  ├── RetryLoop                                     │
  │     ├── OutputGuard (verifica contratto)        │
  │     └── ZarsuitClient (stub / futuro HTTP)      │
  │                                                 │
  ├── SessionManager                                │
  │     ├── SessionLog (JSONL append-only)          │
  │     └── ConsolidationJob (async, modello pesante)│
  │                                                 │
  └── PermissionKernel / Audit (esistenti)          │
                                                    │
  ◄──────── risposta finale all'utente ─────────────┘
```

Separazione invariante:

```text
ZarsuitClient     = unico punto di contatto outbound verso Zarsuit (stub ora)
ContextBroker     = compone il contesto, applica budget adattivo
ContractVerifier  = verifica meccanica output vs attestato
RetryLoop         = orchestra i tentativi, emette UX messages
SessionManager    = ciclo di vita sessione, log JSONL, consolidamento
```

---

## 3. Struttura directory (addizioni a src/segretario/)

```text
src/segretario/
├── flow02/
│   ├── __init__.py
│   ├── models.py              # Pydantic: SecretaryContextRequest, SecretaryTaskRequest,
│   │                          #   RiskAttestation, ZarsuitOutput, RetryAuditEvent
│   ├── context_broker.py      # composizione 3 livelli + budget adattivo
│   ├── character_store.py     # L1: identità statica di Zarsuit
│   ├── working_memory.py      # L2: turni sanificati, sliding window
│   ├── recall_engine.py       # L3: stub (parola chiave search su index.md per ora)
│   ├── attestation.py         # RiskAttestationExchange: build + verify
│   ├── output_guard.py        # verifica contratto sull'output di Zarsuit
│   ├── retry_loop.py          # orchestrazione retry, UX messages, audit
│   ├── zarsuit_client.py      # ZarsuitClient astratto + ZarsuitClientStub
│   └── session/
│       ├── __init__.py
│       ├── manager.py         # SessionManager: apertura, chiusura, doppia condizione
│       ├── log.py             # SessionLog: JSONL append-only
│       └── consolidation.py   # ConsolidationJob: modello asincrono, write-then-rename
└── connectors/
    └── async_llm_client.py    # client Ollama per il modello asincrono (Qwen3.5/3.6)
```

File di test:

```text
tests/
├── test_flow02_models.py
├── test_flow02_context_broker.py
├── test_flow02_attestation.py
├── test_flow02_output_guard.py
├── test_flow02_retry_loop.py
├── test_flow02_session_manager.py
├── test_flow02_session_log.py
└── test_flow02_consolidation.py
```

---

## 4. Contratti — modelli Pydantic

### SecretaryContextRequest

Risposta del Segretario a una richiesta di contesto da parte di Zarsuit.

```python
class SecretaryContextRequest(BaseModel):
    request_id: str              # UUID utente originale (invariato su retry)
    internal_request_id: str     # UUID per questa singola andata verso Zarsuit
    session_id: str
    timestamp: datetime

    # Livello 1 — identità statica
    character_identity: str      # prompt di personalità di Zarsuit

    # Livello 2 — working memory sanificata
    working_memory: list[WorkingMemoryTurn]
    working_memory_tokens: int   # token effettivi usati (≤ tetto per categoria)

    # Livello 3 — recall on-demand (opzionale)
    recall_context: str | None
    recall_tokens: int

    # Attestato di rischio allegato
    attestation: RiskAttestation

    # Budget usato totale
    total_tokens: int
```

### SecretaryTaskRequest

Wrap del messaggio utente inviato a Zarsuit insieme al contesto.

```python
class SecretaryTaskRequest(BaseModel):
    context: SecretaryContextRequest
    user_message: str            # messaggio utente sanificato
    intent_type: IntentType      # CONVERSATIONAL | TASK | MEMORY_LOOKUP
    user_visible_goal: str       # obiettivo leggibile usato nel contratto
```

### RiskAttestation

Il contratto che Zarsuit deve rispettare.

```python
class RiskAttestation(BaseModel):
    attestation_id: str
    request_id: str
    internal_request_id: str
    timestamp: datetime

    # Cosa Zarsuit può usare
    approved_context_projection: list[str]   # campi approvati del contesto

    # Vincoli sull'output
    output_policy: OutputPolicy              # boolean_only | summarized | privacy_projection | free
    max_detail_level: DetailLevel            # minimum_necessary | summary | technical | operational
    allowed_next_steps: list[str]            # azioni che Zarsuit può suggerire

    # Obiettivo verificabile
    user_visible_goal: str
```

### ZarsuitOutput

Output ricevuto da Zarsuit, prima della validazione.

```python
class ZarsuitOutput(BaseModel):
    internal_request_id: str     # deve corrispondere all'attestato
    content: str
    cited_fields: list[str]      # campi del contesto citati da Zarsuit
    suggested_next_steps: list[str]
    detail_level: DetailLevel
    raw_json: dict | None        # per output strutturati
```

### RetryAuditEvent

Registra ogni tentativo nel retry loop.

```python
class RetryAuditEvent(BaseModel):
    request_id: str
    internal_request_id: str
    attempt: int                 # 1 o 2
    outcome: RetryOutcome        # accepted | needs_refinement | rejected
    reason: RetryReason | None   # goal_mismatch | incomplete_output | output_malformed
                                 # | prompt_injection_detected | contract_violation
    timestamp: datetime
```

---

## 5. Budget di contesto adattivo

Il ContextBroker applica un **tetto adattivo per categoria** al livello 2 (working memory).

| Categoria di richiesta | Tetto L2 | Note |
|---|---|---|
| Conversazionale normale | 4 000 token | default |
| Recall esplicito (MEMORY_LOOKUP) | 4 000 + 4 000 recall | L2 + L3 |
| Raffinamento Flow 02 con raw Zarsuit | 2 000–3 000 token | ridotta perché si aggiungono dati raw |
| Retry (secondo o terzo tentativo) | tetto default × 2 | vale la pena massimizzare probabilità di successo |

Regola sliding window:

```text
Compatta (droppa turni vecchi) SOLO se vicini al tetto.
Sotto il tetto non si tocca nulla.
```

Questo minimizza le sanitizzazioni inutili e mantiene la KV cache calda.

---

## 6. Risk Attestation Exchange

Il meccanismo in tre passi:

```text
1. Segretario compone RiskAttestation prima di inviare il contesto a Zarsuit.
2. Zarsuit "firma" ricevendo il contesto (implicito nello stub; esplicito nel client reale).
3. Segretario verifica l'output di Zarsuit contro l'attestato al ritorno.
```

### Checklist di verifica (deterministica)

```text
□ L'output cita solo campi presenti in approved_context_projection?
□ L'output rispetta output_policy (es. boolean_only, summarized)?
□ I suggerimenti dell'output sono tutti in allowed_next_steps?
□ Il detail_level dell'output ≤ max_detail_level?
□ L'output risponde al user_visible_goal (check entità chiave)?
```

L'ultimo check è il solo minimamente semantico: si estraggono le entità chiave dal `user_visible_goal` e si verifica che almeno una appaia nell'output. Se non appare nessuna → `goal_mismatch`.

---

## 7. Retry loop

### Flusso operativo

```text
Segretario invia SecretaryTaskRequest a ZarsuitClient
  │
  ▼
ZarsuitClient.call() → ZarsuitOutput
  │
  ▼
OutputGuard.verify(output, attestation)
  ├── PASS → RefinementEngine.refine(output, raw_context) → risposta utente
  └── FAIL → RetryLoop
              ├── tentativo 1:
              │   UX message: "Zarsuit è tutto fatto, ora si riprende..."
              │   nuovo internal_request_id
              │   projection opzionalmente allargata
              │   budget L2 × 2
              │   → ricomincia da ZarsuitClient.call()
              ├── tentativo 2:
              │   UX message: "ci sto ancora lavorando, un attimo"
              │   → ricomincia da ZarsuitClient.call()
              └── fallimento dopo 2 retry:
                  UX message: "non sono riuscito a completare la richiesta"
                  audit con RetryAuditEvent (reason strutturato)
```

### Regole invarianti

- Il `request_id` originale dell'utente resta invariato per tutti i tentativi.
- Ogni andata verso Zarsuit ha un `internal_request_id` distinto.
- Zarsuit non viene mai informato del motivo del retry. Dal suo punto di vista è una nuova richiesta.
- Il Segretario può allargare autonomamente la projection nel retry (i dati sono già tokenizzati, non è un problema di privacy).

### UX messages

Il messaggio di caricamento appare quando un turno supera **3 secondi**. Non è legato solo al retry: è l'indicatore di loading universale per qualsiasi turno lento.

| Situazione | Messaggio |
|---|---|
| Timeout 3s (qualsiasi causa) | "Zarsuit è tutto fatto, ora si riprende..." |
| Retry 2 in corso | "ci sto ancora lavorando, un attimo" |
| Fallimento finale | "non sono riuscito a completare la richiesta" |

---

## 8. Sessioni

### Apertura

Una sola sessione attiva globale (single-user). `session_id` UUID generato all'apertura.

### Chiusura — doppia condizione

```python
should_close = (
    hours_since_open >= 24
    and minutes_inactive >= 60
)
```

Questa logica garantisce che la sessione **non si chiuda mai durante una richiesta attiva**: se c'è un retry in corso, l'utente ha interagito di recente e il timer di inattività non è maturato.

### Log conversazionale JSONL

Ogni messaggio della sessione viene appeso a:

```text
state/sessions/session_<id>.jsonl
```

Schema entry:

```json
{
  "message_id": "uuid",
  "timestamp": "ISO-8601",
  "session_id": "string",
  "role": "user | zarsuit | segretario",
  "content_ref": "path nel vault o inline string",
  "internal_request_id": "string | null"
}
```

Regole:
- Append-only. Mai riscrivere entry esistenti.
- `content_ref` se il contenuto è un file nel vault; inline per messaggi brevi.
- La proiezione human-readable (`state/sessions/chat.md`) è rigenerata on-demand a partire dal JSONL.

### Cosa succede alla chiusura

```text
1. session_<id>.jsonl viene chiuso (sealed flag).
2. ConsolidationJob viene schedulato nel TaskBoard.
3. Nuova session_<id+1>.jsonl parte vuota.
4. ConsolidationJob gira in background: estrae fatti rilevanti, aggiorna il Vault.
5. Pattern write-then-rename per atomicità (safe su riavvio hub).
```

---

## 9. Modello asincrono

Il consolidamento di fine sessione usa il **modello pesante** (Qwen3.5 9B o 27B) caricato on-demand su Ollama. È sicuro usarlo perché gira solo quando l'utente è inattivo → nessuna contesa VRAM con Gemma.

### Configurazione

```yaml
llm:
  sync_model: "gemma4:e4b"          # sempre caldo, turni utente
  async_model: "qwen3.5:latest"     # on-demand, consolidamento
  async_model_timeout_seconds: 300
```

### AsyncLLMClient

```python
class AsyncLLMClient:
    def consolidate_session(
        self,
        session_jsonl: Path,
        vault_path: Path,
    ) -> ConsolidationResult: ...
```

Responsabilità: caricare il modello, estrarre fatti, aggiornare knowledge nel Vault, scaricare il modello. Implementazione stub nelle fasi 1–4; implementazione reale nella fase 5.

---

## 10. ZarsuitClient

Interfaccia astratta per il punto di contatto outbound verso Zarsuit.

```python
class ZarsuitClient(Protocol):
    def call(self, request: SecretaryTaskRequest) -> ZarsuitOutput: ...

class ZarsuitClientStub:
    """Stub deterministica per test e sviluppo."""
    def call(self, request: SecretaryTaskRequest) -> ZarsuitOutput:
        # restituisce una risposta mock configurabile
        ...
```

Configurazione:

```yaml
zarsuit:
  client: stub           # stub | http (futuro)
  stub_response_file: "tests/fixtures/zarsuit_stub_responses.json"
```

---

## 11. Comandi CLI

```bash
# Flow 02 — contesto e task
uv run segretario zarsuit context-request \
  --request-id <uuid> \
  --goal "testo obiettivo utente" \
  --intent conversational|task|memory_lookup

uv run segretario zarsuit submit-result \
  --internal-request-id <uuid> \
  --output-file result.json

# Sessione
uv run segretario session status
uv run segretario session chat          # proiezione JSONL → chat.md
uv run segretario session close         # chiude manualmente (debug)
uv run segretario session consolidate   # avvia consolidamento manualmente

# Modello asincrono
uv run segretario async-model status    # mostra se il modello asincrono è carico
```

---

## 12. Requisiti di test

### Modelli

- Pydantic validation su tutti i campi obbligatori.
- `internal_request_id` diverso da `request_id`.
- Enum correttamente vincolati.

### ContextBroker

- Budget L2 rispettato per ogni categoria.
- Retry raddoppia il tetto L2.
- Sliding window non tocca i turni recenti se si è sotto il tetto.
- L3 non viene incluso se `intent_type != MEMORY_LOOKUP`.

### Risk Attestation

- Attestato generato contiene i campi corretti.
- Verifica checklist: ciascuna delle 5 condizioni è testata positiva e negativa.
- `goal_mismatch` se entità chiave assenti dall'output.
- `contract_violation` se output cita campo non in `approved_context_projection`.

### Retry loop

- Max 2 retry: al terzo fallimento emette `rejected` + audit.
- `internal_request_id` diverso a ogni tentativo.
- Budget L2 raddoppiato al retry.
- Projection allargata al retry (test con spy su ContextBroker).
- UX messages corretti per ogni stato.
- ZarsuitClientStub usato; nessuna dipendenza da Ollama reale nei test.

### Session manager

- Sessione NON si chiude se `minutes_inactive < 60`.
- Sessione NON si chiude se `hours_since_open < 24`.
- Sessione si chiude solo se entrambe le condizioni sono vere.
- JSONL è append-only: verifica che le entry precedenti non vengano modificate.
- ConsolidationJob viene schedulato nel TaskBoard alla chiusura sessione.
- `write-then-rename` verificato: file intermedio non è il file finale.

### Modello asincrono

- AsyncLLMClient stub non chiama Ollama reale.
- ConsolidationJob non gira se sessione è ancora attiva.

---

## 13. Fasi di implementazione

### Fase 1 — Contratti e ContextBroker

Deliverable:

- `flow02/models.py` — tutti i modelli Pydantic.
- `flow02/context_broker.py` — composizione 3 livelli + budget adattivo.
- `flow02/character_store.py` — L1 identità statica da config.
- `flow02/working_memory.py` — L2 turni, sliding window.
- `flow02/recall_engine.py` — L3 stub (keyword search su `meta/index.md`).
- Test per modelli e ContextBroker.

Acceptance:

```bash
uv run pytest tests/test_flow02_models.py tests/test_flow02_context_broker.py -q
```

### Fase 2 — Risk Attestation + Output Guard

Deliverable:

- `flow02/attestation.py` — AttestationBuilder + ContractVerifier.
- Estensione `flow02/output_guard.py` (integra con attestato).
- Test per attestazione e verifica contratto.

Acceptance:

```bash
uv run pytest tests/test_flow02_attestation.py tests/test_flow02_output_guard.py -q
```

### Fase 3 — Retry loop + ZarsuitClient stub

Deliverable:

- `flow02/zarsuit_client.py` — ZarsuitClient Protocol + ZarsuitClientStub.
- `flow02/retry_loop.py` — orchestrazione retry, UX messages, audit.
- CLI commands `zarsuit context-request` e `zarsuit submit-result`.
- Test per retry loop end-to-end con stub.

Acceptance:

```bash
uv run segretario zarsuit context-request \
  --request-id test-001 --goal "test" --intent conversational
uv run pytest tests/test_flow02_retry_loop.py -q
```

### Fase 4 — Session manager + log JSONL

Deliverable:

- `flow02/session/manager.py` — ciclo di vita sessione, doppia condizione.
- `flow02/session/log.py` — append-only JSONL + proiezione chat.md.
- CLI commands `session status`, `session chat`, `session close`.
- Test per session manager e session log.

Acceptance:

```bash
uv run segretario session status
uv run pytest tests/test_flow02_session_manager.py tests/test_flow02_session_log.py -q
```

### Fase 5 — Consolidamento asincrono + modello pesante

Deliverable:

- `flow02/session/consolidation.py` — ConsolidationJob, write-then-rename.
- `connectors/async_llm_client.py` — AsyncLLMClient (stub prima, poi reale).
- CLI commands `session consolidate`, `async-model status`.
- Test per ConsolidationJob con stub.

Acceptance:

```bash
uv run segretario session consolidate
uv run pytest tests/test_flow02_consolidation.py -q
```

Non passare alla fase successiva prima che la fase corrente sia stabile.

---

## 14. Dipendenze

Nessuna dipendenza nuova richiesta per le fasi 1–4. Pydantic, SQLite, e Typer sono già presenti.

Per la fase 5 (modello asincrono):

```toml
# già presente
httpx>=0.27    # per async_llm_client
```

Il modello Qwen3.5 richiede che l'utente lo scarichi manualmente su Ollama prima di eseguire la fase 5 reale:

```bash
ollama pull qwen3.5:latest
```

---

## 15. Condizioni di stop

L'agente di implementazione deve fermarsi e chiedere se:

1. La struttura del vault è incompatibile con la composizione del livello L3.
2. I modelli `character_store` (L1) dipendono da file di configurazione non ancora definiti.
3. Il TaskBoard non supporta un tipo di job richiesto dal ConsolidationJob.
4. Un'operazione richiederebbe di inviare dati non proiettati a ZarsuitClientStub.
5. Il comportamento del retry loop diverge dalla specifica per un caso non coperto da questa specifica.
6. La doppia condizione di chiusura sessione confligge con uno stato del TaskBoard non previsto.
