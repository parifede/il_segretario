# Prompt Claude Code — Fix 3b-2a: il `summary` deve essere prosa pulita

Repo: `E:\il_segretario` (Python 3.12, `uv`). Branch: `master`.

## 1. Contesto

3b-2a (`/context` reale) è implementato, ma lo smoke ha mostrato un problema di
privacy nel `summary`. Questo prompt lo sistema. Lo step **resta aperto** finché
non è verde.

## 2. Cosa è emerso (il problema)

Smoke 1, `summary` restituito:

```
### knowledge\zarsuit-capabilities.md [§ Backup] (chunk 10, score: 0.786) ...
```

Il `summary` contiene il **plumbing del recall**: path del vault
(`### knowledge\...`, `### self/...`), intestazioni di sezione/chunk e i
punteggi (`(chunk N, score: X)`). La tokenizzazione PII c'è, ma le intestazioni
strutturali sono passate intatte.

Questo **non va**: il `summary` è ciò che il Segretario manda a Zarsuit, e deve
essere una **proiezione pulita**. I path leakano la *struttura* del vault (dice
che esiste una nota tipo `self/info.md`), gli score sono meccanica interna. Sono
roba del Segretario, non devono uscire — anche se i path sono relativi e non
assoluti. zarsOS non lo blocca (controlla `cloud_safe`/`raw_included`, non
scansiona il testo), quindi passerebbe in silenzio.

## 3. Scope

**Entra:**
1. Il `summary` di `/context` deve essere **solo prosa sanificata**: niente path
   vault (`### knowledge\...`, `### self/...` e simili), niente intestazioni
   `### ... [§ ...]`, niente `(chunk N, score: X)`, niente punteggi. La
   tokenizzazione PII (PERSON_TOKEN/PHONE_TOKEN) resta.
2. Fix del falso positivo PII: gli orari tipo `18:23` **non** devono diventare
   `PHONE_TOKEN`.

**NON entra:** `/task`; il contratto e l'enum `status`; auth/bind/porta; il
formato della response (resta `secretary_context_response` come 3b-2a).

## 4. Vincoli operativi

- Decidi tu il punto giusto dello strip: o un passo dedicato nel path `/context`
  (`context_handler`) tra `recall_simple()` e la costruzione del summary, oppure
  dentro `project_private_context`. **Prima di toccare `project_private_context`,
  verifica se è usato altrove** (es. CLI `external answer`): se sì, valuta se lo
  strip dei path va bene anche lì o se conviene farlo solo nel path HTTP. Riporta
  la scelta e il perché.
- Regex PHONE: escludi i pattern orario `HH:MM` dal match telefono, senza
  rompere il riconoscimento dei numeri veri.
- Zero dipendenze nuove. Riusa codice esistente.
- Se trovi un'ambiguità tra questo prompt e il codice, **fermati e segnala**.

## 5. Criteri test (verdi obbligatori)

- Query che pesca chunk con header `### path [§ sez] (chunk N, score: X)` → il
  `summary` risultante **non** contiene `###`, né `knowledge\`/`self/`, né
  `chunk`, né `score`, né i numeri di punteggio. Solo prosa.
- `self/` non compare **mai** nel `summary`.
- Testo con orario `18:23` → **non** diventa `PHONE_TOKEN`; un numero di telefono
  vero → diventa ancora `PHONE_TOKEN`.
- Suite esistente resta verde.

## 6. Smoke reale (output nel report)

- Rifai lo **Smoke 1** (query "backup e configurazione") → incolla il JSON
  completo: il `summary` dev'essere prosa pulita, zero path/score.
- Una query che pesca da `self/` → incolla il JSON: il `summary` non rivela path
  né struttura del vault.

## 7. Reporting (§8)

- File toccati + diff sintetico.
- `uv run pytest -q` **verbatim**.
- Smoke §6 **verbatim** (JSON di risposta inclusi).
- Dove hai messo lo strip e perché; se hai toccato `project_private_context` e se
  è usato altrove.
- Eventuali ambiguità o decisioni minori.

## Pre-flight (operatore)

Backup robocopy pre-step già fatto (senza il vault: `... /XD .git .venv
__pycache__ .pytest_cache vault`). Il developer lo assume come fatto, non tocca git.
