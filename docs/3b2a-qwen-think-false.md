# Prompt Code — disabilita il thinking di qwen3.5:9b (`think=False`)

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## Contesto

Dopo lo switch a `qwen3.5:9b`, la `/context` cade in `partial`: qwen3.5 è un
modello **ragionante** e va in thinking di default (5–10x di latenza) → la sintesi
sfora i 30s → fallback.

Fix: disabilitare il thinking a livello di **chiamata API** con `think=False`.
**NON** usare `/no_think` nel prompt né una variante Modelfile: per qwen3.5 è
documentato come inaffidabile. Deve essere il flag API.

## Cosa fare

1. Fai in modo che le chiamate del **client sync** (l'`OllamaClient` costruito
   da `settings.llm.sync_model`, usato da sintesi `/context` e classificazione)
   passino **`think=False`** alla richiesta Ollama.
   - Aggiungi il supporto a `think` nell'`OllamaClient` se non c'è, e passalo
     come campo **top-level** della richiesta (non dentro `options`).
2. Verifica che la libreria `ollama` Python installata supporti `think`.
   Se troppo vecchia, aggiorna (`pip install -U ollama` — la rete sul PC è ok) e
   dillo nel report.
3. **Verifica empirica** (questa è la parte importante): fai una chiamata reale
   al client sync e conferma che (a) la risposta **non contiene** il blocco di
   reasoning e (b) la latenza è crollata. Se su questa versione di Ollama il
   `think` non viene onorato sull'endpoint `generate`, usa l'endpoint `chat`
   (che lo supporta di sicuro) — ma confermalo con la prova, non a scatola chiusa.

## Scope

**Entra:** solo il `think=False` sul client sync.
**NON toccare:** il modello (`qwen3.5:9b` resta), `_SYNTHESIS_SYSTEM` (prompt
invariato), la pipeline, il fallback, i campi response, le regole privacy, `/task`.

## Test

- `uv run pytest -q` verbatim. Atteso: **464 verdi**.
- Se un test si rompe per via di `think`, segnalalo e fermati (non aggirarlo).

## Lo smoke lo facciamo noi a mano (4-5 giri). Non lanciarlo tu.

## Reporting

- Dove hai messo `think=False` (file:riga) e come (param generate/chat).
- Versione della libreria `ollama` (e se l'hai aggiornata).
- Esito della **prova reale**: latenza prima/dopo + conferma "niente blocco di reasoning nell'output".
- Diff.
- `uv run pytest -q` verbatim.

## Pre-flight (operatore)

Robocopy pre-step fatto (senza `vault`). Developer non tocca git.
