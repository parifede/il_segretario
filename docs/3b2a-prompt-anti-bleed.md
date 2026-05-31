# Prompt Code — Fix 3b-2a: `_SYNTHESIS_SYSTEM` anti instruction-bleed

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## Contesto

Con `qwen3.5:9b` + `think=False` la latenza è risolta e il tono è in 2ª persona,
ma su 5 giri il modello **rigira le regole nel testo**: frasi come "senza
rivelare percorsi o identità", "trascurando dato identificativo come date o
percorsi", e si dà ordini ("Ricorda di mantenere un tono...", "Mantieni...").
Non è un leak di dati (nessun dato vero esce), ma fa trapelare il prompt di
sistema ed è output di bassa qualità.

Fix: **solo** il testo di `_SYNTHESIS_SYSTEM` in
`src/segretario/http_server/context_handler.py`.

## Nuovo valore di `_SYNTHESIS_SYSTEM`

Mantieni la struttura a stringhe concatenate; attento agli apostrofi (`l'utente`,
`l'agente`) → usa una forma di stringa Python valida.

```
Prepari il contesto per Zarsuit, l'agente che parla con l'utente.
In seconda persona rivolto a Zarsuit, descrivi SOLO la situazione: cosa stai facendo con l'utente e a che punto siete.
Esempio del solo taglio, non copiarne il contenuto: "Stai aiutando l'utente con un problema tecnico; finora avete chiarito il punto chiave."
Vietato darti istruzioni: niente "Ricorda di...", "Mantieni...", "Concentrati su...".
Vietato nominare le regole o cosa ometti: mai frasi come "senza rivelare percorsi" o "trascurando date e identificativi". Limitati a non scriverli.
Ometti in silenzio: percorsi, identificativi, email, numeri, date specifiche, URL, citazioni verbatim, dati personali puntuali.
Italiano, prosa semplice, massimo 3 frasi.
```

## Scope

**SOLO** il valore di `_SYNTHESIS_SYSTEM`. **NON toccare:** il modello
(`qwen3.5:9b`), `think=False`, la pipeline, il fallback, i campi response, le
regole privacy (output_guard), il recall, `/task`.

## Test

- `uv run pytest -q` verbatim. Atteso: **464 verdi**.
- Il rispetto del nuovo tono è output LLM → si verifica allo smoke, non con unit
  test deterministici. Non inventare test fragili sul wording.

## Lo smoke lo facciamo noi a mano (5 giri). Non lanciarlo tu.

## Reporting

- Diff della costante.
- `uv run pytest -q` verbatim.

## Pre-flight (operatore)

Robocopy pre-step fatto (senza `vault`). Developer non tocca git.
