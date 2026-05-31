# Prompt Code — Fix 3b-2a: `_SYNTHESIS_SYSTEM` slim (anti-priming) + recon guard

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## Contesto

Il prompt attuale **elenca** cosa omettere ("percorsi, date, ID...") e fa esempi
di cosa NON dire. Effetto "elefante rosa": il modello finisce per nominare proprio
quelle cose ("devi omettere date, ID, percorsi"). Togliamo le liste dal prompt:
il modello scrive solo grounding generico, e la privacy la garantisce il **guard
deterministico già presente a valle** della sintesi.

## Cosa fare

### 1. Sostituire `_SYNTHESIS_SYSTEM`

File: `src/segretario/http_server/context_handler.py`. Mantieni la struttura a
stringhe concatenate; attento agli apostrofi (`l'utente`, `l'agente`,
`nient'altro`) → stringa Python valida.

Nuovo valore (testo esatto):

```
Sei il Segretario. Prepari un breve contesto per Zarsuit, l'agente che parla con l'utente.
In seconda persona rivolto a Zarsuit, digli in modo generale di cosa vi state occupando e a che punto siete.
Resta sul generale, senza dettagli precisi.
Scrivi direttamente il contesto, nient'altro.
Italiano, prosa semplice, 2-3 frasi.
```

### 2. Recon (SOLA LETTURA, nessuna modifica)

Riporta **cosa strippa davvero** il guard che gira dopo la sintesi
(`project_private_context` e `sanitize_user_output`, o come si chiamano nel
pipeline `_project`): quali categorie tolgono in concreto (es. path assoluti?
email? token/credenziali? numeri? date? nomi? URL? stacktrace?). Indica
file:funzione e l'elenco delle categorie coperte. NON modificarli.

## Scope

**Entra:** solo il valore di `_SYNTHESIS_SYSTEM` + il recon (lettura).
**NON toccare:** modello (`qwen3.5:9b`), `think=False`, pipeline, fallback,
guard, campi response, `/task`.

## Test

- `uv run pytest -q` verbatim. Atteso: **464 verdi**.

## Lo smoke lo facciamo noi a mano (5 giri + una query non-specchio). Non lanciarlo tu.

## Reporting

- Diff della costante.
- Recon guard: file:funzione + categorie effettivamente strippate.
- `uv run pytest -q` verbatim.

## Pre-flight (operatore)

Robocopy pre-step fatto (senza `vault`). Developer non tocca git.
