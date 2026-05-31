# Prompt Claude Code — 3b-2a rework: projection con sintesi vera (Gemma)

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## 1. Contesto

`/context` oggi fa "strip header + tokenizza PII + passa il resto". Lo smoke ha
mostrato che passa **contenuto grezzo**: un path assoluto (`E:\ZARSUIT_LOCAL_BACKUPS`)
e metadata di un log privato (`captured_at`, `user_id`) verso il cloud.

L'operatore vuole una **vera sintesi privacy-safe**, non un dump redatto. Una
"privacy projection" deve dare a Zarsuit il *senso* del contesto utile, non il
testo grezzo delle note. Questo prompt rifà la projection. Lo step **resta aperto**.

## 2. Cosa cambia

La projection di `/context` diventa, in ordine:

1. `recall_engine.recall_simple(query)` → contenuto rilevante (come ora).
2. strip header del recall (già fatto, resta).
3. **Sintesi via modello locale sync (Gemma, già usato dal Segretario)** → un
   riassunto conciso e privacy-safe.
4. Tokenizzazione PII (resta).
5. **`sanitize_user_output` (output_guard) come passo finale obbligatorio.**

Il `summary` finale = **prosa sintetica privacy-safe**: il senso del contesto
utile a ragionare, NON il contenuto grezzo. Quindi **niente**: path (relativi o
assoluti), ID, timestamp/metadata di log verbatim, citazioni raw di note private.
La PII resta tokenizzata; l'output_guard cattura path assoluti, token, stacktrace.

## 3. Scope

**Entra:** la rework della projection (sintesi Gemma + output_guard finale).
**NON entra:** `/task`; il contratto e l'enum `status`; auth/bind/porta; il formato
della response (resta `secretary_context_response`).

## 4. Vincoli operativi

- Usa il client **Ollama/Gemma già esistente** nel Segretario (il modello sync,
  `gemma4:e4b`). Niente nuovo client, niente nuove deps. Se non trovi un punto di
  chiamata sync esistente da riusare, **fermati e segnala**.
- Prompt a Gemma: chiedi un riassunto **conciso e privacy-safe** del contesto
  rilevante alla richiesta utente. Istruisci esplicitamente: NON includere path,
  ID, timestamp, contenuto verbatim di note private o dati raw — solo il senso
  necessario a Zarsuit per ragionare. Rispetta `forbidden_context`: ciò che ci
  ricade non entra nella sintesi.
- `sanitize_user_output` come **passo finale obbligatorio** (chiude il leak del
  path assoluto visto nello smoke; rete di sicurezza su token/stacktrace).
- Gestione fallimento Gemma (down/timeout): **niente crash, niente leak**. Fallback
  → status `partial` + summary generica sanificata. Timeout ragionevole (target
  sync ~1-3s, non bloccare all'infinito).
- Status logic invariata (`allowed`/`partial`/`denied`/...).
- Zero deps nuove. Se ambiguità tra prompt e codice → **fermati e segnala**.

## 5. Criteri test (verdi obbligatori)

- Query che pesca da `self/` con dati privati → il `summary` è una **sintesi**:
  NON contiene path, né timestamp/ID/metadata verbatim, né citazioni raw; PII
  tokenizzata.
- `forbidden_context` popolato → il contenuto vietato **non** compare nel summary.
- Contenuto con path assoluto (`C:\...\secrets\`) o token finto (`ya29...`) →
  **redatto** dall'output_guard, non compare nel summary.
- Gemma irraggiungibile → status `partial`, summary generica sanificata, nessun
  crash, nessun leak, audit scritto.
- Suite esistente verde.

## 6. Smoke reale (output nel report)

- Rifai **Smoke 1** (query "backup e configurazione") e **Smoke 2** (query
  conversazioni che pesca da `self/`) → incolla i JSON completi: i `summary`
  devono essere **sintesi pulite**, zero path/timestamp/ID verbatim.
- **Gemma spento** → JSON con status `partial` sanificato, nessun crash.

## 7. Reporting (§8)

- File toccati + diff sintetico.
- `uv run pytest -q` **verbatim**.
- Smoke §6 **verbatim** (JSON inclusi).
- Quale client Gemma hai riusato e dove; il **prompt esatto** dato a Gemma; come
  gestisci timeout/fallback.
- Decisioni minori e ambiguità.

## Pre-flight (operatore)

Backup robocopy pre-step fatto (senza vault). Il developer lo assume, non tocca git.
