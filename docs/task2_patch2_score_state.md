# Claude Code — Task 2 Patch 2: Fix score (distance → similarity) + state store

## Contesto

Worktree `e:\il_segretario\.worktrees\task2-recall-semantic`. NON committare
ancora Task 2. La patch precedente (chunking H2) ha portato indexed=444/445,
errors=0, MA lo smoke test ha rivelato due bug residui che vanno fixati prima
del commit finale.

## Bug 1 — Score "score" è in realtà distance

### Sintomo

Lo smoke test ha mostrato:

```
Hits su "react state management":
  README.md [§ Status values] (chunk 14, score 1.001)
  conversation-log.md (chunk 372, score 1.013)
  ...
  conversation-log.md (chunk 411, score 1.018)
```

Score > 1.0 è impossibile per similarity coseno (range [-1, +1]) o per
similarity normalizzata (range [0, 1]). Inoltre i top-5 sono semanticamente
**inversi** rispetto al match corretto: query inglese di programmazione
React matcha conversazioni in italiano su "andare a Roma" e
"discover_events", che non c'entrano nulla.

Confronto con query semanticamente forti:

```
"zarsuit privacy projection" → score 0.797-0.813 con hit corretti
  (privacy_policy.md, AGENTS.md, zarsuit-capabilities.md)
"ADHD analisi dati" → score 0.662-0.747 con hit corretti
  (conversazione-adhd-qi-dataanalysis.md)
```

**Pattern:** valori 0.6-0.8 = match buoni; valori 0.9-1.0 = rumore.
Significa che il "score" mostrato è in realtà la **distance**: più basso =
migliore. Il sistema ordina ascending pensando di ordinare descending sulla
similarity, quindi i veri top match emergono solo casualmente quando la
distance è bassa.

### Root cause

`sqlite-vec` ritorna **distance** (es. cosine distance `1 - cos_sim` o
distanza L2/Euclidean) nella sua MATCH query. Il codice attuale tratta quel
numero come score (similarity) senza conversione.

### Fix

Tre passi:

**1. Identificare il metric usato**

Verifica come è creata la virtual table `chunk_vectors`. sqlite-vec di
default usa L2 distance (Euclidean) per `vec0`, ma supporta anche cosine.
Cerca nel codice di `sqlite_vec_store.py` la creazione della VIRTUAL TABLE
e la query MATCH.

Probabile pattern attuale:

```python
cursor.execute("""
    SELECT note_path, chunk_index, distance
    FROM chunk_vectors
    WHERE embedding MATCH ?
    ORDER BY distance
    LIMIT ?
""", (serialize_embedding(query_embedding), k))
```

Se il metric è L2: `distance` è in range [0, infinity), più basso = migliore.
Se il metric è cosine: `distance` è in range [0, 2], più basso = migliore.

**2. Convertire distance in similarity**

Modifica la query e/o il post-processing per esporre **similarity** invece di
distance:

- **Per cosine distance:** `similarity = 1 - distance` → range [-1, 1], più
  alto = migliore.
- **Per L2 distance:** `similarity = 1 / (1 + distance)` → range (0, 1],
  più alto = migliore. (Formula standard per convertire distanza in score).

Decidi in base a quale metric usa la tua tabella. Se possibile, **configura
sqlite-vec per usare cosine** (è più adatto a text embeddings):

```python
# Schema con metric cosine esplicito
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
    note_path TEXT,
    chunk_index INTEGER,
    embedding FLOAT[1024] distance=cosine  -- esplicito
);
```

Verifica nella documentazione sqlite-vec corrente la sintassi esatta (è
cambiata tra versioni 0.1.x).

**3. Aggiornare VectorHit per esporre similarity**

In `models.py` (se non già così):

```python
@dataclass
class VectorHit:
    note_path: str
    chunk_index: int
    section_title: str | None
    score: float   # ora è similarity, range [0, 1] (cosine) o (0, 1] (L2)
```

Il campo si chiama `score` ma il commento deve chiarire che è similarity, non
distance. Più alto = più simile.

**4. Ordering della query**

```python
cursor.execute("""
    SELECT note_path, chunk_index, distance
    FROM chunk_vectors
    WHERE embedding MATCH ?
    ORDER BY distance ASC   -- distance ASC = similarity DESC
    LIMIT ?
""", (serialize_embedding(query_embedding), k))

# Poi nel loop:
for row in cursor.fetchall():
    note_path, chunk_index, distance = row
    if metric == "cosine":
        similarity = 1.0 - distance
    else:  # L2
        similarity = 1.0 / (1.0 + distance)
    # ... costruisci VectorHit con score=similarity
```

L'ORDER BY rimane su distance ASC (perché sqlite-vec ritorna distance
nativamente), ma il `similarity` esposto è il valore "umano-friendly" che
ordina descending.

## Bug 2 — `recall status` mostra "Last reindex: never" dopo reindex riuscito

### Sintomo

```
PS> uv run segretario recall reindex
Reindex complete: indexed=0 deleted=0 skipped_unchanged=444 errors=0
PS> uv run segretario recall status
  Last reindex:   never
```

Il `ReindexStateStore` non viene aggiornato quando `indexed=0`, anche se il
reindex è completato con successo (solo skippando tutto).

### Root cause

Nel job scheduler `_run_recall_reindex` o nel comando CLI `recall reindex`,
probabilmente c'è una guardia tipo:

```python
if result.indexed > 0:
    state.set_last_run(now, result.indexed, model)
```

Questa è una condizione sbagliata: lo state va aggiornato **ogni volta che il
reindex completa senza errori bloccanti**, indipendentemente dal count.

### Fix

```python
# Aggiorna state se il reindex è completato (anche se non ha indicizzato nulla)
# Solo gli errori bloccanti (es. embedder down, store inaccessibile) impediscono l'update
if not had_blocking_error:
    state.set_last_run(now, result.indexed, model)
```

Definizione di "errore bloccante": il reindex non ha potuto procedere affatto
(es. embedder health_check fallisce all'avvio). Errori per-nota o per-chunk
non sono bloccanti.

In pratica: aggiorna lo state alla fine di ogni `reindex()` che non ha
sollevato eccezione.

## STEP 1 — Trova il codice da modificare

Identifica i file da toccare:

```powershell
cd e:\il_segretario\.worktrees\task2-recall-semantic

# Cerca dove sqlite-vec MATCH è usato
Get-ChildItem -Path src/segretario -Recurse -Filter "*.py" | Select-String -Pattern "MATCH|distance" -List

# Cerca dove state.set_last_run è chiamato
Get-ChildItem -Path src/segretario -Recurse -Filter "*.py" | Select-String -Pattern "set_last_run|indexed >" -List
```

File probabilmente coinvolti:
- `src/segretario/recall/sqlite_vec_store.py` (per il fix score)
- `src/segretario/recall/models.py` (chiarire `VectorHit.score` come similarity)
- `src/segretario/scheduler/jobs.py` o `src/segretario/cli.py` (per il fix state store)

## STEP 2 — Modifiche

### Per il bug 1 (score)

In `sqlite_vec_store.py`:

1. Verifica/imposta il metric esplicito nella CREATE VIRTUAL TABLE (cosine
   preferibile per text embeddings; se la tabella esiste già con metric
   diverso, dovremo droppare e ricrear lo schema — vedi STEP 4 migration).
2. Modifica la query: ordina su distance ASC (più basso = più simile).
3. Nel codice che costruisce `VectorHit`, converti `distance` in `similarity`:
   - Cosine: `similarity = 1.0 - distance`
   - L2: `similarity = 1.0 / (1.0 + distance)`
4. Documenta nel docstring di `VectorHit.score` che il valore è similarity
   (range cosine [0, 1] approssimativo per text embeddings, o (0, 1] per L2),
   più alto = migliore.

### Per il bug 2 (state)

Nel callsite che chiama `state.set_last_run()` (probabilmente
`scheduler/jobs.py::_run_recall_reindex` e/o `cli.py::recall_reindex_command`):

Rimuovi qualsiasi guardia `if result.indexed > 0`. L'aggiornamento deve
avvenire ogni volta che `indexer.reindex()` ritorna senza sollevare eccezione.

```python
try:
    result = indexer.reindex()
except Exception as exc:
    # Errore bloccante: NON aggiornare state
    logger.error("recall.reindex failed: %s", exc)
    return f"recall.reindex: failed: {exc}"

# Reindex completato (anche con 0 indexed): aggiorna state
state.set_last_run(now, result.indexed, model)
return f"recall.reindex: indexed={result.indexed} ..."
```

Verifica che il messaggio di ritorno dia conto di tutti i casi:
- `indexed=N`: report normale
- `indexed=0 skipped_unchanged=N`: report "tutto già aggiornato, niente da fare"
- Errore bloccante: report dell'errore

## STEP 3 — Test

Aggiungi/aggiorna test in `tests/test_recall_vector_store.py` (o file
equivalente):

```python
def test_vector_store_query_returns_similarity_not_distance():
    """Lo score esposto deve essere similarity (più alto = migliore), non distance."""
    # Setup store con 2 vettori: uno molto simile alla query, uno molto diverso
    store = SqliteVecStore(...)
    very_similar = [1.0, 0.0, 0.0, ...]  # 1024 dim
    very_different = [-1.0, 0.0, 0.0, ...]
    query = [1.0, 0.0, 0.0, ...]

    store.upsert_chunk("similar.md", 0, None, very_similar, "h1", "n1")
    store.upsert_chunk("different.md", 0, None, very_different, "h2", "n2")

    hits = store.query(query, k=2)

    # Il primo hit (più simile) deve avere score più ALTO
    assert hits[0].score > hits[1].score
    # Score in range valido per similarity
    assert 0.0 <= hits[0].score <= 1.0
    assert 0.0 <= hits[1].score <= 1.0
    # Lo score del molto-simile deve essere vicino a 1.0
    assert hits[0].score > 0.9


def test_vector_store_query_orders_by_similarity_descending():
    """I risultati sono ordinati con il match migliore (similarity più alta) per primo."""
    store = SqliteVecStore(...)
    # Inserisci 5 vettori a distanza crescente da query
    for i in range(5):
        embedding = [1.0 - 0.1*i, 0.0, ...]
        store.upsert_chunk(f"note{i}.md", 0, None, embedding, f"h{i}", f"n{i}")

    query = [1.0, 0.0, ...]
    hits = store.query(query, k=5)

    # Verifica ordering: score decrescente
    for i in range(len(hits) - 1):
        assert hits[i].score >= hits[i+1].score


def test_reindex_updates_state_even_if_indexed_zero():
    """Lo state store viene aggiornato anche quando reindex non indicizza nulla nuovo."""
    # Setup: indicizza una nota, poi rifai reindex senza modifiche
    vault = _make_vault_with_notes(tmp_path, ["test.md"])
    settings = _settings(tmp_path)

    # Prima esecuzione
    state = ReindexStateStore(settings.recall.state_path)
    result1 = run_reindex_job(settings)
    first_run = state.get_last_run()
    assert first_run is not None

    # Seconda esecuzione (tutto unchanged)
    time.sleep(0.1)  # garantisce timestamp distinti
    result2 = run_reindex_job(settings)
    second_run = state.get_last_run()
    assert second_run is not None
    assert second_run > first_run  # state aggiornato anche se indexed=0


def test_reindex_does_not_update_state_on_blocking_error():
    """Se l'indexer solleva eccezione non gestita, lo state NON viene aggiornato."""
    # Setup: forza l'indexer a sollevare eccezione (es. mock embedder che raise)
    # Verifica che state.last_run resti None o invariato
```

Aggiorna anche i test esistenti che asserivano sui valori di `score` di
RecallHit/VectorHit, perché ora i range sono diversi (similarity invece di
distance).

## STEP 4 — Migrazione schema (se necessario)

Se il metric era L2 e cambi a cosine, lo schema della VIRTUAL TABLE cambia.
sqlite-vec NON supporta migrazione in-place del metric. Devi:

1. All'avvio del SqliteVecStore, verificare il metric corrente:
   ```python
   cursor.execute("SELECT sql FROM sqlite_master WHERE name='chunk_vectors'")
   row = cursor.fetchone()
   if row and "distance=cosine" not in row[0]:
       logger.warning("Recall vector store uses non-cosine metric; recreating schema with cosine. ALL EMBEDDINGS WILL BE DROPPED, full reindex required.")
       cursor.execute("DROP TABLE chunk_vectors")
       cursor.execute("DELETE FROM indexed_chunks")
       # Ricrea con cosine
       ...
   ```

2. Logga chiaramente che serve un reindex completo.

**Se il metric era già cosine** (controllare!), basta:
- Aggiungere la conversione `1.0 - distance` nel codice
- Nessuna migration necessaria

## STEP 5 — Smoke test reale

DOPO i test verdi:

```powershell
cd e:\il_segretario\.worktrees\task2-recall-semantic

# Pulizia per evitare contaminazione da run precedenti con score sbagliato
Remove-Item state\recall.sqlite -Force -ErrorAction SilentlyContinue
Remove-Item state\recall_last_run.json -Force -ErrorAction SilentlyContinue

# Reindex completo
uv run segretario recall reindex

# Status: deve mostrare "Last reindex: <timestamp recente>"
uv run segretario recall status

# Query semanticamente forti (sappiamo cosa esiste nel vault)
uv run segretario recall search "zarsuit privacy projection" --k 5
uv run segretario recall search "ADHD analisi dati" --k 5
uv run segretario recall search "data analysis coursera" --k 5

# Query "rumore" (semanticamente NON dovrebbe matchare bene)
uv run segretario recall search "react state management" --k 5

# Reindex idempotente: NON deve essere skippato (guardia 15 min)
# ma deve fare skipped_unchanged=444 e aggiornare lo state
uv run segretario recall reindex
uv run segretario recall status   # Last reindex deve essere RECENTE
```

### Criteri di successo

1. **Score in range valido:** tutti gli score devono essere in [0.0, 1.0]
   (mai > 1.0 e mai < 0.0). Se compaiono valori > 1.0 il fix score è
   ancora rotto.

2. **Ordering semanticamente corretto:**
   - Query "zarsuit privacy projection" → top hit deve essere
     `meta/privacy_policy.md` o `AGENTS.md` o `zarsuit-capabilities.md`,
     score > 0.6.
   - Query "ADHD analisi dati" → top hit deve essere
     `self/character/conversazione-adhd-qi-dataanalysis.md`, score > 0.6.
   - Query "data analysis coursera" → top 3 hit devono essere file
     `raw/extracted/*coursera*.md`, score > 0.5.

3. **Query "rumore" produce hit con score bassi:**
   - Query "react state management" → score top non superiore a 0.5 (la query
     è in inglese su programmazione web, il vault non ne parla). Se ci sono
     comunque top hits con score > 0.7, qualcosa è ancora sbagliato.

4. **State store funziona:**
   - Dopo reindex, `recall status` mostra "Last reindex: <ISO timestamp>"
     (non "never").
   - Dopo SECONDO reindex (skip per 15-min guardia), `recall status` mostra
     timestamp **aggiornato** rispetto al primo run (sì, anche se è skippato
     per guardia: il fatto stesso che la guardia abbia eseguito conta).
   - **Eccezione:** se la guardia 15-min skippa il reindex *prima* di
     chiamare `indexer.reindex()`, il timestamp NON deve essere aggiornato
     perché il reindex non è stato eseguito. Solo i reindex effettivamente
     eseguiti (anche se con indexed=0 perché skipped_unchanged) aggiornano
     lo state.

## STEP 6 — Commit

SOLO se tutti i criteri di successo passano:

```
fix(recall): correct similarity score and state persistence

Two bugs discovered in Task 2 smoke test:

1. Score was distance, not similarity (values > 1.0, inverted ordering).
   Fix: configure sqlite-vec with cosine metric (or convert L2 to
   similarity via 1/(1+d)). Expose `similarity = 1 - distance` in
   VectorHit.score. Top results now have highest scores, range [0, 1].

2. ReindexStateStore was not updated when indexed=0 (e.g. all chunks
   unchanged). Fix: update state on any successful reindex completion,
   not only when new content was indexed. Only blocking exceptions skip
   the state update.

- Schema migration: chunk_vectors recreated with cosine metric (if needed)
- N new tests for similarity ordering, range validity, state persistence
- Manual smoke test: all queries return semantically correct top hits
  with scores in [0, 1], state correctly persisted across runs.

Closes Task 2 (with patch 1 + patch 2).
```

## STEP 7 — Aggiornare project notes

Dopo il commit, aggiorna `docs/project-notes-consolidated.md`:

- Sezione 1: Task 2 marcato come ✅ chiuso
- Sezione 4: rimuovere bug 4a e 4b (entrambi fixati)
- Sezione 2: aggiungere alla cronologia Task 2 il fix score + state
- Sezione 5: aggiungere lezione appresa "verifica metric distance vs
  similarity nei vector store"

## Cosa NON fare

- NON re-implementare il chunking. La patch precedente è OK.
- NON cambiare il modello embedding. Lo abbiamo già fissato a mxbai.
- NON re-discutere le decisioni di design Task 2.
- NON committare prima che lo smoke test passi tutti i criteri.
- NON considerare i ~100 chunks oversize come bloccanti per Task 2. Sono
  registrati come follow-up (sezione 3g delle note progetto). Per ora il
  85% indicizzato deve essere sufficiente per chiudere Task 2.

## Stop and ask

Fermati se:

- Il metric corrente di sqlite-vec non si capisce dalla documentazione (cosine
  vs L2 vs altro).
- La migration richiede di droppare TUTTI i chunk già indicizzati e tu non
  sei sicuro che sia giusto (è giusto: reindex è veloce, niente di critico
  va perso).
- Lo smoke test mostra ancora score > 1.0 dopo il fix (significa che la
  conversione non è applicata in qualche code path).
- Lo smoke test mostra ancora top hits semanticamente sbagliati anche dopo il
  fix (significa che il problema è altro, non l'ordering).
- Il fix state store rompe test esistenti del job scheduler.
