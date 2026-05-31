# Prompt Code — `/context`: onora `forbidden_context` a livello recall

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## Contesto

Il campo `forbidden_context` (lista di stringhe) è già nello schema della
richiesta `/context` ma è **accettato e ignorato** (smoke `forbidden-001`
restituisce 200 ma il summary include ancora "agenda" anche se l'avevamo
vietata).

Lo onoriamo a livello **recall**, non sintesi: scartiamo i chunk del recall
che contengono uno qualsiasi dei termini vietati, **prima** che la sintesi
li veda. Deterministico, niente LLM coinvolto.

## Cosa fare

In `src/segretario/http_server/context_handler.py`, nel `_project` (o dove
sta la pipeline recall → strip → synth → guard):

1. Dopo `recall_engine.recall_simple(...)`, **prima** della sintesi, applica
   un filtro: per ogni hit/chunk testuale, se contiene almeno uno dei termini
   di `forbidden_context` come **substring case-insensitive**, scartalo.
2. Se `forbidden_context` è assente, `None`, o lista vuota → **no-op** (non
   filtrare nulla, comportamento attuale).
3. Se dopo il filtro **non resta nulla**, gestisci con grazia: restituisci
   `status="partial"` con summary generico sanificato (stesso stile del
   fallback "sintesi non raggiungibile", ma con un messaggio appropriato a
   "contesto non disponibile entro i vincoli richiesti"). Niente crash,
   niente leak.
4. Il filtro lavora sui chunk/hit prima dell'eventuale `_strip_recall_headers`
   e prima della concatenazione che va alla sintesi — l'importante è che la
   sintesi non veda mai il testo dei chunk filtrati.

## Scope

**Entra:** solo il filtro + il suo punto di chiamata + la gestione del caso
"tutto filtrato".

**NON toccare:** lo schema (`forbidden_context` è già accettato),
`_SYNTHESIS_SYSTEM`, il modello, `think=False`, il guard a valle, il fallback
del modello giù, i campi della response, `/task`.

## Test

Aggiungi unit test (mocka l'LLM come fanno gli altri test della pipeline):

- `forbidden_context` con un termine che compare in qualche chunk → quei
  chunk non arrivano alla sintesi.
- `forbidden_context` con termine in **case diverso** → comunque filtrato
  (verifica del case-insensitive).
- `forbidden_context` assente / vuoto / `None` → nessun filtro (comportamento
  invariato).
- `forbidden_context` che svuota tutto il recall → `status="partial"` con
  summary generico sanificato, niente eccezioni.

Atteso: **464 verdi precedenti + i nuovi**.

## Lo smoke lo facciamo noi (rilanciamo `forbidden-001`). Non lanciarlo tu.

## Reporting

- Diff (filtro + call site + eventuale fallback "tutto filtrato").
- Nomi dei nuovi test e cosa coprono in una riga ciascuno.
- `uv run pytest -q` verbatim.

## Pre-flight (operatore)

Robocopy pre-step fatto (senza `vault`). Developer non tocca git.
