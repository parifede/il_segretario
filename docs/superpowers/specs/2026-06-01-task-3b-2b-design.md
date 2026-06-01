# Design — Task 3b-2b: `/task` logica reale (il_segretario)

> Data: 2026-06-01
> Baseline pytest: 469 test verdi
> Contratto di riferimento: `docs/secretary_bridge_contract.md`
> Spec di implementazione: `docs/task-3b-2b-prompt-implementazione.md`

---

## Scope

`POST /task` sostituisce la risposta hardcoded dello stub con logica reale:
**classificazione + preparazione risposta + gating conferma**.
Nessuna esecuzione side-effecting reale (niente invio email, scrittura vault,
azioni Gmail/Calendar). L'esecuzione vera dipende dal Taskboard (GAP #6, task
futuro).

`requires_confirmation` = *bozza pronta, azione NON eseguita*.

---

## File toccati

| File | Modifica |
|------|----------|
| `src/segretario/http_server/task_handler.py` | **nuovo** — tutta la logica |
| `src/segretario/http_server/app.py` | sostituisce stub, aggiunge `character_store` interno |
| `src/segretario/policies/output_guard.py` | aggiunge `guard_zarsuit_schema_leak` |
| `src/segretario/config/settings.py` | aggiunge `LLMSettings.sync_model_keep_alive: int = -1` |
| `src/segretario/connectors/ollama_client.py` | aggiunge `keep_alive: int` al costruttore |
| `tests/test_http_server.py` | riscrive `test_task_happy_path`, aggiunge ~15 test |

`policies/permissions.py` — **non si tocca**.
`stub_responses.py` — rimane ma non viene più chiamato da `/task`.

---

## Flusso di esecuzione — `build_task_response_real`

```
request body (TaskRequestBody.secretary_task_request dict)
  │
  ├─ 1. Parsing
  │       request_id ← validate_safe_request_id(root["request"]["request_id"])
  │             ValueError → propaga → 400 (gestito da app.py come oggi)
  │       domain, action_type, action_name ← root["task"][...]
  │             chiavi mancanti → default sicuri ("unknown", "unknown", "")
  │
  ├─ 2. Decision
  │       if domain in _REFUSED_DOMAINS
  │           → refused, reason=refused_domain
  │       constants = _ACTION_MAP.get((domain, action_type))
  │       if constants is None
  │           → refused, reason=unmapped_action
  │       strictest(PermissionKernel.decision_for(c) for c in constants):
  │           ALLOW   → completed
  │           CONFIRM → requires_confirmation
  │           DENY / PROJECT → refused, reason=kernel_denied   ← difensivo
  │
  ├─ 3. Generazione content
  │       completed / requires_confirmation → LLM via OllamaClient.generate()
  │             LocalModelUnavailable → eccezione gestita → state=failed (vedi §Errori)
  │       refused / failed              → content TEMPLATO STATICO (no LLM)
  │
  ├─ 4. Guard — guard_zarsuit_schema_leak(content)
  │       fired → state=failed, content templato, guard_fired=True
  │       (fail-closed: NON emettere testo redatto/parziale)
  │
  ├─ 5. Sanitize — sanitize_user_output(content)   [OAuth / path guard esistente]
  │
  ├─ 6. Audit — audit_log.append_event("secretary_task_request", {...})
  │       OK  → audit.stored=True, response 200
  │       FAIL → HTTP 503, audit_unavailable (vedi §Errori)
  │
  └─ 7. Build response dict → JSONResponse 200
```

---

## Tre livelli di risposta HTTP

| Situazione | HTTP | Body |
|---|---|---|
| `request_id` invalido / envelope malformato | 400 | `{"ok": false, "error": "invalid_request"}` |
| Fallimento esecuzione, audit OK | 200 | `{"secretary_task_result": {... state: "failed", audit.stored: true}}` |
| Fallimento scrittura audit (qualsiasi stato) | **503** | `{"ok": false, "error": "audit_unavailable"}` |

Nessun 200 è valido senza `audit.stored = true`. Zarsuit mappa HTTP 503 a
fail-closed content-free.

---

## `_ACTION_MAP` e `_REFUSED_DOMAINS`

### Domini sempre rifiutati (wildcard `*`)

```python
_REFUSED_DOMAINS: frozenset[str] = frozenset({
    "private_context_lookup",  # territorio di /context
    "secret_or_forbidden",
    "dangerous_action",        # shell.execute = DENY_BY_DEFAULT
    "agent_activation",        # nessuna capability remota
    "system_diagnostic",       # Zarsuit-handled (codex §14)
    "bacheca",                 # Taskboard non esposto via HTTP (GAP #6)
    "mixed",                   # ambiguo; clarification rimanda
    "unknown",
})
```

### Tabella azioni

`_ACTION_MAP: dict[tuple[str, str], tuple[str, ...]]`
Chiave: `(domain, action_type)`. Valore: tupla di **simboli** `PermissionKernel.*`
(non stringhe literal scritte a mano). Un nome sbagliato diventa `AttributeError`
al caricamento del modulo, non un test rosso silenzioso.

| (domain, action_type) | simboli PermissionKernel | classe → stato | provenienza |
|---|---|---|---|
| (gmail, read_only) | `GMAIL_READ` | ALLOW → completed | classifiers.js L164 |
| (gmail, draft) | `GMAIL_DRAFT` | ALLOW → completed | L171 |
| (gmail, external_effect) | `GMAIL_SEND`, `GMAIL_DELETE`, `GMAIL_ARCHIVE` | CONFIRM → requires_confirmation | L170 |
| (calendar, read_only) | `CALENDAR_READ` | ALLOW → completed | L164 |
| (calendar, schedule) | `CALENDAR_SCHEDULE` | ALLOW → completed | L168 |
| (calendar, write) | `CALENDAR_CREATE`, `CALENDAR_CREATE_WITH_ATTENDEES`, `CALENDAR_MODIFY` | **CONFIRM** (split: CREATE=ALLOW, altri=CONFIRM → più stretta) | L172 |
| (calendar, external_effect) | `CALENDAR_DELETE`, `CALENDAR_ACCEPT`, `CALENDAR_DECLINE` | CONFIRM → requires_confirmation | L170 |
| (vault, read_only) | `VAULT_READ`, `VAULT_SEARCH` | ALLOW → completed | L164 |
| (vault, write) | `KNOWLEDGE_WRITE`, `SELF_PROFILE_WRITE` | **CONFIRM** (split: KNOWLEDGE=ALLOW, SELF_*=CONFIRM → più stretta) | L172 |
| (memory, read_only) | `VAULT_SEARCH` | ALLOW → completed | L164 |
| (memory, write) | `KNOWLEDGE_WRITE`, `SELF_THOUGHTS_WRITE` | **CONFIRM** (split → più stretta) | L172 |
| (web_research, read_only) | `WEB_PUBLIC_QUERY` | ALLOW → completed | L173-174 |
| (vault_commands, write) | `KNOWLEDGE_WRITE`, `SELF_PROFILE_WRITE` | **CONFIRM** (split → più stretta) | L172 |

**Sintassi nel codice**:
```python
from segretario.policies.permissions import PermissionKernel as PK

_ACTION_MAP: dict[tuple[str, str], tuple[str, ...]] = {
    ("gmail", "read_only"): (PK.GMAIL_READ,),
    ("gmail", "external_effect"): (PK.GMAIL_SEND, PK.GMAIL_DELETE, PK.GMAIL_ARCHIVE),
    # ...
}
```

Il test di esistenza costanti è ridondante per la parte simboli (ImportError/AttributeError
al boot) ma resta utile come documentazione vivente della lista attesa.

### Risoluzione strictest

```python
_DECISION_ORDER = {ALLOW: 0, CONFIRM: 1, DENY: 2, PROJECT: 2}

def _strictest(decisions):
    return max(decisions, key=lambda d: _DECISION_ORDER[d])
```

`DENY` e `PROJECT` mappano entrambi a refused (`reason=kernel_denied`) — ramo
difensivo anche se nessuna costante attuale lo raggiunge.

---

## Guard — `guard_zarsuit_schema_leak`

```python
@dataclass(frozen=True)
class GuardResult:
    fired: bool
    redactions: list[str]
```

### Quattro pattern (Q4 da `docs/secretary_bridge_contract.md`)

**Pattern 1 + 2 (fusi) — chiavi schema interne**

Definire **una sola volta** le due liste; i pattern vengono generati da esse
(niente regex scritte a mano per-token → nessun typo silenzioso):

```python
# Identificatori inequivoci: non compaiono mai in output utente legittimo.
# Beccati come token nudo (word-boundary): match anche non quotati.
_SCHEMA_KEYS_UNAMBIGUOUS: tuple[str, ...] = (
    "secretary_task_request",
    "secretary_context_request",
    "risk_attestation",
    "zarsuit_task_output_for_secretary",
    "zarsuit_execution_input",
    "secretary_routing_directive",
)

# Chiavi generiche: parole inglesi comuni → richiedi contesto JSON quotato.
_SCHEMA_KEYS_GENERIC: tuple[str, ...] = (
    "tool_call",
    "function_call",
    "arguments",
    "internal_tool",
)
```

Generazione pattern:
```python
import re
_PAT_UNAMBIGUOUS = re.compile(
    "|".join(r"\b" + re.escape(k) + r"\b" for k in _SCHEMA_KEYS_UNAMBIGUOUS)
)
_PAT_GENERIC_JSON = re.compile(
    "|".join(r'"' + re.escape(k) + r'"' for k in _SCHEMA_KEYS_GENERIC)
)
```

Se uno qualsiasi dei due pattern fa match → fired=True.

Il test anti-drift asserisce che `_SCHEMA_KEYS_UNAMBIGUOUS` e
`_SCHEMA_KEYS_GENERIC` contengano esattamente le keyword della tabella Q4
del contratto.

**Pattern 3 — tag XML**

Regex: `<(system|developer|internal_schema|zarsuit_internal_schema|tool_schema|function_schema)\b`

**Pattern 4 — prefissi di riga**

Regex su righe inizianti con:
`role:\s*(system|developer)`, `zarsuit_internal_schema:`, `schema_internal:`,
`internal_schema:`, `tool_schema:`, `function_schema:`, `recipient:\s*functions`

### Anti-drift

Test che asserisce che le liste di keyword nel codice Python coincidono con
la tabella Q4 del contratto (pin esplicito). Forma non-quotata
(`"Il campo secretary_task_request è..."`) → guard scatta.

---

## Audit fields

```python
{
    "request_id":       request_id,          # echo della request
    "mapped_action":    action_constant,     # prima costante risolta (o "none")
    "kernel_decision":  decision.value,      # "allow"/"confirm"/"deny"/...
    "result_state":     state,               # completed/requires_confirmation/refused/failed
    "output_sanitized": True,
    "guard_fired":      guard_result.fired,
    "audit_reason":     reason,              # refused_domain/unmapped_action/kernel_denied/ok
}
```

Nomi scelti per non finire in `hash_chain.SENSITIVE_KEYS`
(nessuno contiene `content`/`text`/`raw`/`body`/`auth`/`token`/`secret`).

---

## Config e injection

### `LLMSettings.sync_model_keep_alive`

```python
sync_model_keep_alive: int = -1  # -1 = sempre residente
```

### `OllamaClient` — `keep_alive` nel costruttore

```python
def __init__(self, *, model, base_url, timeout_seconds=120,
             think=None, keep_alive=-1, client=None):
    ...
    self.keep_alive = keep_alive

def generate(self, prompt, system=None):
    payload = {...}
    payload["keep_alive"] = self.keep_alive
    ...
```

Nota: quando arriverà il consolidamento async / model-swap (Fase 5), `keep_alive`
dovrà coordinarsi con un unload-before-consolidate per non contendere la VRAM
(16 GB) col modello pesante.

### `create_app` — injection `CharacterStore`

```python
_character = CharacterStore.from_config(settings.character.identity)
```

Costruito internamente nel ramo `llm_client=None` di `create_app`.
Non aggiunto come parametro opzionale per non rompere i test esistenti che
chiamano `create_app` senza di esso.

**`_FakeLLMClient`** nei test non cambia — è iniettato direttamente, non
tocca il costruttore di `OllamaClient`.

---

## Invarianti risposta (da contratto)

Ogni stato deve soddisfare:
- `request.request_id` = echo (validato)
- `ownership.output_owner = "segretario"`, `zarsuit_processing_allowed = false`, `zarsuit_editing_allowed = false`
- `final_response.audience = "user"`
- `final_response.content` = stringa non vuota
- `privacy.raw_private_data_exposed_to_zarsuit = false`, `output_sanitized_by_secretary = true`
- `audit.stored = true` (solo se audit OK; altrimenti 503)
- `confirmation.required = true` **sse** `state == requires_confirmation`; `false` altrimenti

---

## Test da scrivere

1. **Esistenza costanti**: itera tutte le costanti in `_ACTION_MAP` e asserisce che siano in `PermissionKernel`.
2. **ALLOW → completed**: `(gmail, read_only)` → `state=completed`, `required=false`.
3. **CONFIRM → requires_confirmation**: `(gmail, external_effect)` → `state=requires_confirmation`, `required=true`.
4. **Split → più stretta**: `(calendar, write)` → `requires_confirmation` (non completed).
5. **refused_domain**: `(secret_or_forbidden, anything)` → `state=refused`, `required=false`.
6. **unmapped_action**: `("pippo", "pluto")` → `state=refused`, reason=`unmapped_action`.
7. **kernel_denied** (mock): forzare `decision_for` a ritornare DENY → `state=refused`, reason=`kernel_denied`.
8. **content non vuoto**: per ogni stato.
9. **Guard — schema nel JSON**: `{"secretary_task_request": "x"}` nel content → `failed`, content templato.
10. **Guard — tag XML**: `<system>...` nel content → `failed`.
11. **Guard — inequivoco non quotato**: `"Il campo secretary_task_request è..."` → fired.
12. **Guard anti-drift**: keyword list nel codice = lista Q4.
13. **Audit chiamato**: `fake_audit.events` non vuoto dopo ogni call.
14. **Audit fail → 503**: `append_event` che lancia → HTTP 503.
15. **LocalModelUnavailable → failed**: LLM raises → `state=failed`, content templato, `audit.stored=true`.
16. **Riscrittura `test_task_happy_path`**: forma invariata, valori reali.
