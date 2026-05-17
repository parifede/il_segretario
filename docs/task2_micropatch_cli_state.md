# Claude Code — Task 2 Micro-patch: Fix "Last reindex: never" nel CLI

## Contesto

Worktree `e:\il_segretario\.worktrees\task2-recall-semantic`. Task 2 quasi
chiuso, 417/417 test verdi, smoke test ha confermato similarity score corretto
e ordering semanticamente perfetto.

**Resta un solo bug**: `recall status` mostra "Last reindex: never" anche dopo
un `recall reindex` riuscito (sia con `indexed>0` sia con `indexed=0
skipped_unchanged=444`).

## Diagnosi del problema

La Patch 2 precedente diceva di fixare il bug "state store non aggiornato".
Il subagent ha verificato `scheduler/jobs.py::_run_recall_reindex` e ha
constatato che lì la chiamata a `set_last_run` era già incondizionata, quindi
ha aggiunto un test e dichiarato il fix completo.

**Ma il bug è altrove.** Il comando `segretario recall reindex` lanciato da
CLI **non passa per `_run_recall_reindex` del scheduler**. Passa per il CLI
command handler diretto in `cli.py` (o file equivalente), che probabilmente:

- non chiama `state.set_last_run()` affatto, OPPURE
- lo chiama solo se `result.indexed > 0` (la guardia che credevamo fosse
  nel scheduler era invece qui)

Lo smoke test conferma la diagnosi: dopo `uv run segretario recall reindex`
con `indexed=444`, `recall status` mostra ancora "never". Lo state file
`state/recall_last_run.json` o non viene mai creato, o non viene aggiornato.

## STEP 1 — Trova il code path reale del CLI

```powershell
cd e:\il_segretario\.worktrees\task2-recall-semantic

# Cerca il comando CLI recall reindex
Get-ChildItem -Path src/segretario -Recurse -Filter "*.py" | Select-String -Pattern "recall.*reindex|reindex.*command|@.*command.*recall" -List

# Cerca tutti i posti dove set_last_run viene chiamato
Get-ChildItem -Path src/segretario -Recurse -Filter "*.py" | Select-String -Pattern "set_last_run" -List

# Cerca dove ReindexStateStore è istanziato
Get-ChildItem -Path src/segretario -Recurse -Filter "*.py" | Select-String -Pattern "ReindexStateStore\(" -List
```

Probabili file:
- `src/segretario/cli.py` — comando `recall reindex` (Typer command)
- `src/segretario/scheduler/jobs.py` — `_run_recall_reindex` (già fixato)
- `src/segretario/recall/state.py` — `ReindexStateStore` (logica corretta)
- `src/segretario/recall/indexer.py` — `VaultIndexer.reindex()` (ritorna risultato)

Il path da fixare è probabilmente il CLI command in `cli.py`.

## STEP 2 — Verifica diagnosi

Lancia direttamente:

```powershell
# Vedi cosa contiene lo state file (se esiste)
Get-Content state/recall_last_run.json -ErrorAction SilentlyContinue
# Atteso: errore o file inesistente

# Lancia reindex
uv run segretario recall reindex

# Vedi se il file ora esiste
Get-Content state/recall_last_run.json -ErrorAction SilentlyContinue
# Atteso: file vuoto/inesistente → CONFERMA che set_last_run non viene chiamato dal CLI
```

Se invece il file viene creato ma con contenuto vuoto/sbagliato, il bug è in
`set_last_run()` stesso (ma è già testato, quindi improbabile).

## STEP 3 — Fix

Nel CLI command (probabilmente `cli.py`), assicurati che dopo
`indexer.reindex()` venga chiamato `state.set_last_run()`.

Pattern atteso (esempio, da adattare al codice reale):

```python
@recall_app.command("reindex")
def recall_reindex_command(
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Reindex semantic recall."""
    settings = load_settings()

    if not settings.recall.enabled:
        typer.echo("Recall is disabled in config (recall.enabled=false). Nothing to reindex.")
        return

    # ... costruzione indexer ...

    typer.echo("Recall index: reindexing...")
    try:
        result = indexer.reindex(force=force, dry_run=dry_run)
    except Exception as exc:
        typer.echo(f"Reindex failed: {exc}", err=True)
        raise typer.Exit(code=1)

    # *** FIX CRITICO: aggiorna state DOPO il reindex riuscito ***
    state = ReindexStateStore(settings.recall.state_path)
    now = datetime.now(timezone.utc)
    state.set_last_run(now, result.indexed, settings.recall.embedding_model)

    typer.echo(
        f"Reindex complete: indexed={result.indexed} "
        f"deleted={result.deleted} "
        f"skipped_unchanged={result.skipped_unchanged} "
        f"errors={len(result.errors)}"
    )
```

**Punto chiave**: `state.set_last_run()` viene chiamato **incondizionatamente**
dopo che `indexer.reindex()` ritorna senza eccezioni. Indipendente da
`result.indexed` value. Stessa logica del scheduler.

**Se il CLI ha già un blocco di set_last_run con guardia**, rimuovi la guardia.

## STEP 4 — Verifica anche `recall status` legge correttamente

Mentre sei nel codice, verifica anche `recall status` command. Pattern atteso:

```python
@recall_app.command("status")
def recall_status_command():
    settings = load_settings()
    state = ReindexStateStore(settings.recall.state_path)
    last = state.get_last_run()

    last_str = last.isoformat() if last else "never"
    # ... resto del report ...
```

`get_last_run()` deve ritornare un `datetime | None`, e "never" appare solo
se è None. Se il code path è corretto qui e il bug è solo nel reindex command,
basta fixare step 3.

## STEP 5 — Test

Aggiungi a `tests/test_recall_state_store.py` (o equivalente) un test che
verifica il flusso CLI end-to-end:

```python
def test_cli_recall_reindex_updates_state(tmp_path, monkeypatch):
    """Il comando CLI 'recall reindex' aggiorna il state store."""
    # Setup vault con 1 nota
    vault = _make_vault_with_notes(tmp_path, ["test.md"])
    config_path = _make_config(tmp_path, vault, recall_enabled=True)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config_path))

    # Verifica state inizialmente vuoto
    state_path = tmp_path / "state" / "recall_last_run.json"
    assert not state_path.exists()

    # Esegui il command CLI (usa Typer runner o invocazione diretta)
    runner = CliRunner()
    result = runner.invoke(app, ["recall", "reindex"])
    assert result.exit_code == 0
    assert "Reindex complete" in result.output

    # Verifica state ora popolato
    assert state_path.exists()
    state = ReindexStateStore(state_path)
    last = state.get_last_run()
    assert last is not None
    assert isinstance(last, datetime)


def test_cli_recall_status_reads_state_after_reindex(tmp_path, monkeypatch):
    """Dopo recall reindex, recall status mostra timestamp non 'never'."""
    # Setup come sopra
    # ... reindex ...
    runner = CliRunner()
    runner.invoke(app, ["recall", "reindex"])

    result = runner.invoke(app, ["recall", "status"])
    assert result.exit_code == 0
    assert "Last reindex:" in result.output
    assert "never" not in result.output  # deve mostrare timestamp, non never


def test_cli_recall_reindex_updates_state_even_when_all_unchanged(tmp_path, monkeypatch):
    """Anche con indexed=0 skipped_unchanged=N, lo state si aggiorna."""
    # Setup: indicizza una volta
    runner = CliRunner()
    runner.invoke(app, ["recall", "reindex"])
    state_path = tmp_path / "state" / "recall_last_run.json"
    first_mtime = state_path.stat().st_mtime

    # Aspetta un attimo, rilancia (tutto unchanged)
    time.sleep(0.05)
    result = runner.invoke(app, ["recall", "reindex"])
    assert "skipped_unchanged" in result.output or "indexed=0" in result.output

    # State aggiornato anche se non c'era niente da indicizzare
    second_mtime = state_path.stat().st_mtime
    assert second_mtime > first_mtime
```

## STEP 6 — Smoke test reale

DOPO i test verdi:

```powershell
cd e:\il_segretario\.worktrees\task2-recall-semantic

# Pulizia
Remove-Item state\recall.sqlite -Force -ErrorAction SilentlyContinue
Remove-Item state\recall_last_run.json -Force -ErrorAction SilentlyContinue

# Reindex
uv run segretario recall reindex
# Atteso: indexed=444 (circa) errors=0

# Status: DEVE mostrare timestamp, NON "never"
uv run segretario recall status
# Atteso: Last reindex: 2026-05-17T... (ISO timestamp)

# Verifica file state esiste e ha contenuto
Get-Content state\recall_last_run.json
# Atteso: { "last_run": "...", "indexed_count": 444, "embedding_model": "mxbai-embed-large" }

# Secondo reindex (15-min guardia attiva? Verifica)
# Se guardia è attiva, il reindex NON viene eseguito → state NON aggiornato
# Se guardia non è attiva (es. soglia 0), reindex viene eseguito → state aggiornato
uv run segretario recall reindex
uv run segretario recall status
# Atteso: timestamp aggiornato (o invariato se guardia ha skippato)
```

## Criteri di successo

1. `recall status` dopo `recall reindex` mostra timestamp ISO, NON "never"
2. File `state/recall_last_run.json` esiste e contiene dati validi
3. Nuovi test in step 5 passano
4. Tutti i test esistenti continuano a passare (417+)

## STEP 7 — Commit finale Task 2

SOLO se i criteri sono soddisfatti:

```
fix(recall): CLI command updates reindex state on completion

The Patch 2 fix was applied to scheduler/jobs.py but the CLI command
'segretario recall reindex' uses a separate code path in cli.py which
was not calling state.set_last_run(). 'recall status' showed
"Last reindex: never" even after successful reindex.

Fix: in CLI recall_reindex_command, call state.set_last_run() after
indexer.reindex() returns successfully, mirroring the scheduler logic.

- 3 new CLI integration tests for reindex/status state persistence
- All 420+ tests passing
- Manual smoke test: recall status now shows correct timestamp

Closes Task 2 (chunking H2 + score similarity + state persistence in CLI).
```

## STEP 8 — Aggiornamento note progetto

Dopo il commit finale di Task 2, aggiorna
`docs/project-notes-consolidated.md`:

- **Sezione 1 (Piano):** Task 2 marcato come ✅ chiuso, commit hash
- **Sezione 2 (Decisioni):** confermare cronologia Task 2 con i 3 round di patch
- **Sezione 4 (Bug):** rimuovere bug 4a (score) e 4b (state) — entrambi fixati
- **Sezione 5 (Lezioni):** aggiungere lezione "fix completo richiede di
  verificare TUTTI i code path, non solo quello apparente". Il bug della
  Patch 2 era diviso in due posti, Claude Code ha fixato uno e dichiarato
  chiuso. Lezione: il test era nel posto sbagliato perché non simulava il
  reale invocation pattern dell'utente (CLI invece di scheduler).
- **Sezione 1 (Piano):** aggiungi **Task 3.5: Prompt injection detection**
  tra Task 3 (integrazione HTTP) e Task 4 (wizard UX):

  ```markdown
  - 🔲 **Task 3.5: Prompt injection detection**
    - Da fare DOPO integrazione HTTP reale (Task 3) e PRIMA del wizard (Task 4)
    - Motivazione: finché ZarsuitClient era stub, il rischio era teorico.
      Con client reale, l'output di Zarsuit può contenere tentativi di
      injection nei contratti di attestato di rischio (§3.2 del documento
      decisioni Flow 02).
    - Opzioni di implementazione (§8.1 del documento decisioni):
      1. Regex/keyword list su pattern noti
      2. Detection strutturale via JSON schema
      3. LLM classifier dedicato (Gemma)
    - Combo proposta: strutturale + regex safety net + LLM classifier per edge cases
  ```

## Cosa NON fare

- NON re-implementare chunking, score, state store. Solo fix CLI path.
- NON cambiare modello embedding.
- NON committare prima dello smoke test passato.
- NON dimenticare di rimuovere lo state vecchio prima dello smoke test
  (potrebbe contaminare il test).

## Stop and ask

Fermati se:

- Il CLI command non si trova facilmente (cerca con grep prima).
- Il fix richiede modifiche oltre `cli.py` (es. nuove dipendenze, refactor
  della costruzione delle dipendenze).
- Lo state file viene creato ma con contenuto wrong (probabile bug in
  `ReindexStateStore.set_last_run()` stesso, non gestito qui).
- Dopo il fix, `recall status` ancora mostra "never" (bug più profondo,
  forse in `get_last_run` o in come `recall status` legge lo state).
