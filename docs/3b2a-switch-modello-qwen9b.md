# Prompt Code — /context: cambia modello di sintesi → `qwen3.5:9b`

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## Contesto

La sintesi con `gemma4:e4b` è **instabile**: a volte rigurgita le proprie
istruzioni nel summary ("stai affrontando la richiesta di riassumere... ricordati
di ignorare..."). gemma4:e4b è piccolo e l'instruction-following è il suo punto
debole. Proviamo `qwen3.5:9b` (già scaricato), che segue meglio le regole.

## Cosa fare (UNA variabile sola)

1. Trova dove è definito `settings.llm.sync_model` (il modello usato dalla
   sintesi `/context`, passato a `OllamaClient` in `create_app`).
2. **Riporta**: file e riga del default attuale, e se esiste un **override da
   env var** (nome esatto). Se l'override da env esiste, **NON toccare il
   codice**: dicci solo il nome della variabile, lo settiamo noi.
3. Se NON c'è override da env, cambia il default di `sync_model` da
   `"gemma4:e4b"` a `"qwen3.5:9b"`.

## Scope

**SOLO** il valore di `sync_model`. **NON toccare:**
- `_SYNTHESIS_SYSTEM` (il prompt resta identico: cambiamo una variabile alla volta);
- la pipeline, il fallback, i campi della response, le regole privacy, `/task`.

## Test

- `uv run pytest -q` verbatim. Atteso: **464 verdi** (i test mockano l'LLM, il
  nome del modello non dovrebbe contare).
- Se un test **hardcoda** `"gemma4"`, **NON cambiarlo**: segnalalo e fermati.
- Conferma che il server parte e che in `create_app` l'`OllamaClient` riceve
  `"qwen3.5:9b"`.

## Lo smoke lo facciamo noi a mano (4-5 giri). Non lanciarlo tu.

## Reporting

- Dove sta `sync_model` (file:riga) + eventuale env var.
- Diff, se hai cambiato il default.
- `uv run pytest -q` verbatim.

## Pre-flight (operatore)

Robocopy pre-step fatto (senza `vault`). Developer non tocca git.
