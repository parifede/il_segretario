# Prompt Code — Fix 3b-2a: `_SYNTHESIS_SYSTEM` in seconda persona

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## Contesto

Lo smoke di `/context` ha mostrato un summary in **terza persona / osservatore**
("la conversazione verte su...", "gli interlocutori discutono..."). `/context`
deve dare a Zarsuit un **grounding in seconda persona**, restando privacy-safe.
NON deve estrarre fatti personali (quello è l'attestato, fuori scope).

Cambia **solo** la costante `_SYNTHESIS_SYSTEM` in
`src/segretario/http_server/context_handler.py` (righe ~25-30). Niente altro.

## Nuovo valore di `_SYNTHESIS_SYSTEM`

Testo da usare (mantieni la struttura a stringhe concatenate; **attento agli
apostrofi** `l'utente`/`l'agente`: usa una forma di stringa Python valida):

```
Stai preparando il contesto per Zarsuit, l'agente che parla con l'utente.
Scrivi in seconda persona rivolgendoti a Zarsuit (es. "Stai aiutando l'utente con...", "Finora avete...").
Non scrivere come osservatore esterno: mai "gli interlocutori", mai "la conversazione verte".
Dai solo il filo utile per continuare: di cosa si tratta, a che punto siete, cosa è bene tenere a mente.
Non includere: percorsi di file, identificativi, email, numeri, date specifiche, URL, citazioni verbatim, dati personali puntuali.
Prosa semplice in italiano, massimo 3 frasi.
```

## Scope

**Entra:** solo il valore della costante.
**NON entra:** la pipeline, il fallback, i campi della response, le regole
privacy/output_guard, il recall, `/task`.

## Test

- I test esistenti restano **verdi** (il privacy-check non cambia).
- Il tono in 2ª persona è output dell'LLM → si verifica allo smoke, non con un
  unit test deterministico. Non inventare test fragili sul wording.

## Smoke reale (output nel report)

Avvia/ricarica il server e manda una `/context` di **grounding**:

```json
{ "secretary_context_request": {
  "request_id": "tone-001",
  "user_request_full": "Di cosa abbiamo parlato di recente e a che punto siamo?",
  "intent": "memory_lookup"
}}
```

Incolla il **JSON completo**. Atteso: `summary` in **2ª persona rivolto a
Zarsuit**, niente "gli interlocutori"/"la conversazione verte", e sempre
privacy-pulito (niente path, ID, numeri, date specifiche).

## Reporting

- Diff della costante.
- `uv run pytest -q` verbatim.
- Smoke verbatim (JSON incluso).

## Pre-flight (operatore)

Backup robocopy pre-step fatto (senza vault). Developer non tocca git.
