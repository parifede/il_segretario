# Claude Code — Task 2 v2: Recall L3 semantico con state machine

## Contesto operativo

Questo è Task 2 di un piano per chiudere `il_segretario` prima dell'avvio
reale con zarsOS.

**Piano completo aggiornato (5 task):**
- ✅ Task 1: Fix scheduling backup. Chiuso, commit `43b4533`, 353 test verdi.
- 🟡 Task 2: Recall L3 semantico via embeddings + state machine. **Questo task.**
- 🔲 Task 3: Wizard di attivazione e downgrade UX (lato zarsOS).
- 🔲 Task 4: Integrazione `il_segretario` ↔ zarsOS via HTTP.
- 🔲 Task 5: Documentazione utente operativa.

Stato attuale del recall (`src/segretario/flow02/recall_engine.py`):
- 26 righe, stub keyword-based su `meta/index.md`.
- Splitta query in parole >3 caratteri, grep case-insensitive, tronca a `max_tokens*4` caratteri.
- Zero ranking, zero semantica.

Vault reale (445 note totali):
- `raw/` 302, `knowledge/` 81, `output/` 30, `self/` 9, `meta/` 7, `Clippings/` 5, `docs/` 4
- File `.md` UTF-8, frontmatter YAML opzionale, wikilinks Obsidian.

Modelli embedding già scaricati su Ollama:
- `nomic-embed-text:latest` (274 MB, 768 dim) — non usato
- `mxbai-embed-large:latest` (669 MB, 1024 dim) — **modello scelto**

## STEP 0 — BACKUP OBBLIGATORIO (PRIMA DI QUALSIASI ALTRA AZIONE)

Prima di toccare anche solo un file, esegui:

```powershell
uv run segretario vault backup
```

Atteso: `il_segretario_vault_manual_<YYYYMMDD-HHMMSS>.zip` in
`E:\ZARSUIT_LOCAL_BACKUPS\` con sidecar `.sha256`. Report dimensione, hash,
path completo nel summary finale.

Se il backup fallisce per qualsiasi motivo, fermati e chiedi prima di
procedere. È il punto di rollback se Task 2 va male.

## Decisioni di design (già prese, NON re-discutere)

Tutte prese nella chat di design 2026-05-17. Definitive.

1. **Approccio retrieval:** Embeddings puro. Architettura aperta a FTS5
   futuro (interfaccia `Retriever` astratta, oggi un solo `EmbeddingRetriever`).
2. **Modello embedding:** `mxbai-embed-large` (1024 dim).
3. **Chunking:** nota intera. Una nota = un vettore. Coerente con LLM Wiki di Karpathy.
4. **Storage:** `sqlite-vec`. Pattern repository per nascondere backend
   dietro interfaccia `VectorStore`.
5. **Pre-filtering privacy:** nessuno. Recall pesca anche da `self/`. Privacy
   projection responsabilità del `ContextBroker` downstream (§3.6 di
   `docs/secretary-flow02-decisions.md`).
6. **Re-indexing:** Scheduled job + invalidazione su ingest. Guardia
   temporale: skip se ultimo reindex < 15 min fa.
7. **NUOVO — State machine a 5 stati:** il `RecallEngine` non ritorna più
   `str | None`. Ritorna un oggetto strutturato `RecallResult` con stato,
   contenuto (se eseguito), modalità usata, e info per il wizard quando
   richiesto. **Il wizard vero è Task 3**; in Task 2 prepariamo solo i
   dati che servono.
8. **NUOVO — Fallback keyword non automatico:** il keyword stub esiste
   come funzione `_keyword_search()` chiamabile, ma NON è il fallback
   automatico quando il semantico è disabilitato. Viene invocato solo
   quando l'utente sceglie esplicitamente "Non ora" o "Procedi keyword"
   (logica che Task 3 implementerà). In Task 2 il `RecallEngine` espone
   un metodo `keyword_search(query)` che Task 3 chiamerà quando serve.

## Architettura del modulo `recall/`

Nuovo package `src/segretario/recall/`. Il file esistente
`src/segretario/flow02/recall_engine.py` resta come **facade compatibile
con l'API esistente** (vedi STEP 7).

```
src/segretario/recall/
├── __init__.py
├── models.py              # RecallResult, RecallEngineState, WizardType, RecallHit, ecc.
├── state_machine.py       # determina lo stato corrente del recall in base alla config + runtime
├── retriever.py           # Protocol Retriever
├── embedding_retriever.py # implementazione embeddings
├── vector_store.py        # Protocol VectorStore
├── sqlite_vec_store.py    # implementazione sqlite-vec
├── embedder.py            # client Ollama
├── indexer.py             # scansione vault + hash-based diff
├── chunker.py             # WholeNoteChunker
├── keyword_search.py      # legacy keyword stub estratto, riutilizzabile
├── health.py              # health check embedder/store per distinguere READY vs UNAVAILABLE
└── state.py               # ReindexStateStore (pattern come BackupStateStore)
```

## STEP 1 — Dipendenze

In `pyproject.toml`:

```toml
dependencies = [
  # ... esistenti ...
  "sqlite-vec>=0.1.0",
  "ollama>=0.4.0",   # se non già presente
]
```

`uv sync` e verifica. Se Ollama client già installato con versione diversa,
NON forzare upgrade: nota e procedi.

## STEP 2 — `models.py` — Tipi e enum

Crea `src/segretario/recall/models.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RecallEngineState(str, Enum):
    """Stato osservabile del RecallEngine per una specifica query.

    Cinque valori coprono tutti i casi reali:
    - SEMANTIC_READY: tutto ok, query eseguita semanticamente
    - SEMANTIC_DISABLED_PROMPT: semantico disabilitato in config, utente non
      ha ancora visto/rifiutato il wizard. Task 3 mostrerà wizard ATTIVAZIONE.
    - SEMANTIC_DISABLED_DISMISSED: utente ha rifiutato il wizard ("Non più
      chiedermelo"). Nessun wizard, keyword silenzioso permanente.
    - SEMANTIC_UNAVAILABLE_TRANSIENT: semantico abilitato ma in runtime non
      risponde (Ollama down, embedder errore, indice corrotto). Task 3
      mostrerà wizard DOWNGRADE.
    - SEMANTIC_DISABLED_OVERRIDE: utente ha scelto "Non ora" in questo turno;
      vale solo per questa query, wizard riapparirà al prossimo trigger.
    """
    SEMANTIC_READY = "semantic_ready"
    SEMANTIC_DISABLED_PROMPT = "semantic_disabled_prompt"
    SEMANTIC_DISABLED_DISMISSED = "semantic_disabled_dismissed"
    SEMANTIC_UNAVAILABLE_TRANSIENT = "semantic_unavailable_transient"
    SEMANTIC_DISABLED_OVERRIDE = "semantic_disabled_override"


class RecallMode(str, Enum):
    """Modalità effettivamente usata per la query."""
    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    NONE = "none"  # nessuna ricerca eseguita (es. wizard required prima)


class WizardType(str, Enum):
    """Tipo di wizard che Task 3 dovrà mostrare. None se nessuno."""
    ACTIVATION = "activation"   # wizard A: "Vuoi attivare il semantico?"
    DOWNGRADE = "downgrade"     # wizard B: "Semantico non risponde, procedi keyword?"


@dataclass
class RecallHit:
    """Singolo match restituito dal retriever."""
    note_path: str
    score: float
    content_preview: str


@dataclass
class RecallResult:
    """Risultato strutturato di una chiamata a RecallEngine.recall().

    Task 3 leggerà questo oggetto e deciderà:
    - Se wizard_required è settato: mostrarlo all'utente, raccogliere risposta,
      richiamare RecallEngine con override appropriato.
    - Altrimenti: usare content come risultato finale del recall L3.
    """
    state: RecallEngineState
    mode_used: RecallMode
    content: str | None = None
    hits: list[RecallHit] = field(default_factory=list)
    wizard_required: WizardType | None = None
    wizard_context: dict[str, Any] = field(default_factory=dict)
    # wizard_context conterrà info per costruire il wizard:
    # ACTIVATION: { "description": "...", "performance_note": "...", ... }
    # DOWNGRADE: { "failure_reason": "...", "last_known_good": "...", ... }
    error: str | None = None  # eventuale messaggio di errore tecnico
```

Documenta nel docstring di `RecallResult` che è **l'interfaccia di contratto
verso Task 3**: tutti i campi che ci sono devono restare; aggiungere nuovi
campi è ok, rimuoverli o cambiarli no.

## STEP 3 — Schema `sqlite-vec`

Database **separato** dal taskboard: `state/recall.sqlite`. Motivi: lifecycle
indipendente, restore parziale possibile, schema isolato.

```sql
CREATE TABLE IF NOT EXISTS indexed_notes (
    path TEXT PRIMARY KEY,           -- path relativo al vault
    content_hash TEXT NOT NULL,      -- sha256 del contenuto al momento dell'indexing
    indexed_at TEXT NOT NULL,        -- ISO timestamp
    chunk_count INTEGER NOT NULL,    -- per ora sempre 1 (whole-note)
    embedding_model TEXT NOT NULL    -- es. "mxbai-embed-large"
);

CREATE VIRTUAL TABLE IF NOT EXISTS note_vectors USING vec0(
    note_path TEXT,
    embedding FLOAT[1024]
);

CREATE INDEX IF NOT EXISTS idx_indexed_notes_hash ON indexed_notes(content_hash);
```

Inizializzazione sqlite-vec:

```python
import sqlite3
import sqlite_vec

conn = sqlite3.connect(db_path)
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)
```

Documenta inline perché è facile dimenticarlo in nuovi entry point.

## STEP 4 — `embedder.py` (client Ollama)

```python
class OllamaEmbedder:
    def __init__(self, model: str, base_url: str, timeout_seconds: int = 60) -> None: ...

    def embed(self, text: str) -> list[float]:
        """Ritorna vettore 1024-dim. Solleva EmbedderError su fail."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch. Loop oggi, ottimizzabile dopo."""

    def health_check(self) -> bool:
        """True se Ollama risponde e il modello è caricato. Usato dallo state machine."""
```

Requisiti:
- Client ufficiale Python `ollama`.
- Endpoint default `http://127.0.0.1:11434`, configurabile via `RecallSettings`.
- Modello default `mxbai-embed-large`, configurabile.
- Gestisci `ollama.ResponseError`, `ConnectionError`, timeout → raise
  `EmbedderError` con messaggio chiaro che lo state machine può inserire in
  `wizard_context["failure_reason"]`.
- `embed_batch`: log warning + skip nota su singolo fail. Idempotenza al ri-run.
- Testi >8000 char: log warning (mxbai potrebbe troncare).
- `health_check`: tenta un embed di una stringa breve di prova ("test").
  Se ok, ritorna True. Su qualsiasi eccezione, False. Timeout breve (~5s).

## STEP 5 — `VectorStore` e `SqliteVecStore`

`vector_store.py` (Protocol):

```python
class VectorStore(Protocol):
    def upsert(self, note_path: str, embedding: list[float], content_hash: str) -> None: ...
    def delete(self, note_path: str) -> None: ...
    def query(self, embedding: list[float], k: int = 5) -> list[VectorHit]: ...
    def get_indexed_hash(self, note_path: str) -> str | None: ...
    def list_indexed_paths(self) -> set[str]: ...
    def health_check(self) -> bool: ...   # connessione + estensione vec funzionante
```

`sqlite_vec_store.py`: implementazione concreta.

Requisiti:
- `upsert` atomico in transazione. Idempotente.
- `query` distanza coseno (controlla l'API sqlite-vec corrente per il nome
  esatto della funzione; al momento del prompt era `vec_distance_cosine`).
- `delete` rimuove da entrambe le tabelle.
- `list_indexed_paths` ritorna set per diff veloce.
- Schema CREATE IF NOT EXISTS.
- `health_check`: una query a vuoto sulla tabella vec. False su eccezione.

## STEP 6 — `Indexer` con hash-based diff

```python
class VaultIndexer:
    def __init__(
        self,
        vault_path: Path,
        store: VectorStore,
        embedder: OllamaEmbedder,
        chunker: Chunker,
        skip_paths: list[str],
    ) -> None: ...

    def reindex(self, force: bool = False) -> ReindexResult: ...

    def update_note(self, note_path: Path) -> bool:
        """Re-indicizza singola nota. Chiamato da ingest dopo write."""
```

Algoritmo `reindex`:
1. Scansione `vault_path/**/*.md`, escludendo `skip_paths`
   (default: `["raw/elaborati"]`).
2. Per ogni file: calcola sha256, confronta con `store.get_indexed_hash(path)`,
   se diverso/assente → indicizza.
3. Note nello store ma non più nel filesystem → `store.delete(path)`.
4. Ritorna `ReindexResult(indexed, deleted, skipped_unchanged, errors)`.

Errori non bloccanti: lista in `errors`, prosegui, log WARNING.

**Convenzione progetto:** `raw/elaborati/` mai scansionato (vedi `AGENTS.md`
"Vault Structure"). Verifica come altri job (lint, watcher) rispettano la
regola e segui lo stesso pattern.

**NON pre-filtrare `self/`.** Indicizza tutto. Privacy = broker downstream.

## STEP 7 — `state_machine.py` — Determina lo stato corrente

Cuore della nuova logica. File nuovo `src/segretario/recall/state_machine.py`:

```python
from __future__ import annotations
from segretario.recall.models import RecallEngineState, WizardType
from segretario.recall.embedder import OllamaEmbedder
from segretario.recall.vector_store import VectorStore


class RecallStateMachine:
    """Determina lo stato del recall per una specifica query.

    Inputs:
    - settings (RecallSettings: enabled, user_dismissed_wizard, ...)
    - embedder e store (per health checks)
    - override per-call: il chiamante può forzare "usa keyword per questo turno"
      passando override_mode="keyword_once" (uscita scelta "Non ora" del wizard)
      o "keyword_proceed" (uscita "Procedi keyword" del wizard downgrade)

    Output: tupla (state, wizard_required, wizard_context).
    """

    def __init__(self, settings: RecallSettings, embedder: OllamaEmbedder | None, store: VectorStore | None) -> None:
        self._settings = settings
        self._embedder = embedder
        self._store = store

    def evaluate(self, override_mode: str | None = None) -> tuple[RecallEngineState, WizardType | None, dict]:
        """Decisione completa di stato per una singola query.

        Logica:
        1. Se override_mode == "keyword_once" → SEMANTIC_DISABLED_OVERRIDE
        2. Se override_mode == "keyword_proceed" → SEMANTIC_UNAVAILABLE_TRANSIENT (ma esegui keyword)
        3. Se enabled=False e user_dismissed_wizard=True → SEMANTIC_DISABLED_DISMISSED
        4. Se enabled=False e user_dismissed_wizard=False → SEMANTIC_DISABLED_PROMPT + wizard ACTIVATION
        5. Se enabled=True:
           a. health_check embedder + store: se entrambi ok → SEMANTIC_READY
           b. altrimenti → SEMANTIC_UNAVAILABLE_TRANSIENT + wizard DOWNGRADE
        """
        ...
```

Implementazione completa: vedi flowchart sopra. Ogni transizione deve essere
testabile in isolamento (vedi STEP 12).

`wizard_context` per ACTIVATION:
```python
{
    "description": "Il recall semantico ti permette di cercare nella tua memoria con parafrasi e sinonimi, non solo parole esatte.",
    "performance_note": "La prima indicizzazione richiede ~5-10 minuti per il tuo vault.",
    "model": "mxbai-embed-large",
}
```

`wizard_context` per DOWNGRADE:
```python
{
    "failure_reason": "Ollama non risponde all'endpoint http://127.0.0.1:11434",  # da embedder error
    "last_successful_query": <ISO timestamp ultimo embed riuscito, se disponibile>,
    "diagnostic_hint": "Verifica che Ollama sia in esecuzione. Comando: ollama list",
}
```

## STEP 8 — `EmbeddingRetriever` e `keyword_search.py`

`embedding_retriever.py`:

```python
class EmbeddingRetriever:
    def __init__(self, vault_path: Path, store: VectorStore, embedder: OllamaEmbedder) -> None: ...

    def search(self, query: str, k: int = 5) -> list[RecallHit]:
        query_embedding = self.embedder.embed(query)
        vec_hits = self.store.query(query_embedding, k=k)
        return [self._enrich(hit) for hit in vec_hits if self._note_exists(hit)]
```

Note tecniche:
- Se la nota referenziata dal vector hit non esiste più (drift indice/FS),
  skip + log WARNING.
- `content_preview`: 500 char, evita di spezzare wikilinks `[[...]]` a metà.

`keyword_search.py` — Estrai la logica del vecchio stub in funzione standalone:

```python
def keyword_search(index_path: Path, query: str, max_tokens: int = 4000) -> str | None:
    """Ricerca keyword originale, estratta come funzione pura riutilizzabile.

    NON è il fallback automatico: viene chiamata esplicitamente quando il
    RecallStateMachine decide che lo stato corrente richiede modalità keyword
    (override "Non ora" del wizard ACTIVATION, "Procedi keyword" del wizard
    DOWNGRADE, o stato DISMISSED).
    """
    if not index_path.exists():
        return None
    text = index_path.read_text(encoding="utf-8", errors="replace")
    keywords = [w.lower() for w in query.split() if len(w) > 3]
    if not keywords:
        return None
    lines = text.splitlines()
    matched = [line for line in lines if any(kw in line.lower() for kw in keywords)]
    if not matched:
        return None
    result = "\n".join(matched)
    char_limit = max_tokens * 4
    return result[:char_limit] if len(result) > char_limit else result
```

## STEP 9 — Refactor `flow02/recall_engine.py` (facade)

Il file esistente è importato da `cli.py` e `context_broker.py`. Mantieni il
path. Cambia internamente.

**API esterna nuova** (breaking change minimo, da gestire nei chiamanti):

```python
class RecallEngine:
    """L3: recall semantico con state machine.

    Facade: delega al modulo segretario.recall. Espone API a 2 livelli:
    - recall(query, ...): nuova API che ritorna RecallResult strutturato.
      Da usare dai chiamanti nuovi (Task 3 use case).
    - recall_simple(query, max_tokens): API legacy che ritorna str | None.
      Usata internamente come adapter per i chiamanti vecchi che non
      sanno gestire il RecallResult. Logica: chiama recall(), e se lo
      stato richiede wizard, ritorna None (chi chiama recall_simple non
      può gestire wizard). Se lo stato è READY/DISMISSED/OVERRIDE,
      ritorna il content.
    """

    def __init__(self, index_path: Path, recall_settings: RecallSettings | None = None) -> None: ...

    def recall(self, query: str, override_mode: str | None = None, k: int = 5) -> RecallResult:
        """Nuova API strutturata. Da usare dai chiamanti Task-3-aware."""
        ...

    def recall_simple(self, query: str, max_tokens: int = 4000) -> str | None:
        """API legacy compatibile col vecchio stub. NON triggera wizard.

        Se il sistema richiede wizard, ritorna None silenziosamente. Use cases
        dove non c'è UI per il wizard (test, batch jobs, ecc.) chiamano questa.
        """
        result = self.recall(query)
        if result.wizard_required is not None:
            return None
        return result.content

    def keyword_search(self, query: str, max_tokens: int = 4000) -> str | None:
        """Ricerca keyword esplicita. Chiamato da Task 3 quando l'utente
        sceglie 'Non ora' o 'Procedi keyword' nei wizard."""
        from segretario.recall.keyword_search import keyword_search
        return keyword_search(self._index_path, query, max_tokens)
```

**Backward compatibility:** trova tutti i chiamanti attuali di `RecallEngine.recall()`:

```powershell
Get-ChildItem -Path src/segretario -Recurse -Filter "*.py" | Select-String -Pattern "\.recall\(" -List
```

Per ciascuno:
- Se è un test: probabilmente va aggiornato per usare `recall_simple()` o
  asserire sul nuovo `RecallResult`.
- Se è `context_broker.py`: aggiorna per usare `recall_simple()` PER ORA.
  Task 3 lo aggiornerà per usare `recall()` e gestire wizard.
- Se è `cli.py`: il vecchio comando deve continuare a funzionare.
  Usa `recall_simple()`.

Documenta nel commit ogni callsite modificato.

## STEP 10 — `RecallSettings`

In `src/segretario/config/settings.py`:

```python
class RecallSettings(BaseModel):
    enabled: bool = False  # defensive default
    user_dismissed_wizard: bool = False  # set a True quando utente sceglie "Non più chiedermelo"
    embedding_model: str = "mxbai-embed-large"
    ollama_base_url: str = "http://127.0.0.1:11434"
    db_path: Path = Path("state/recall.sqlite")
    state_path: Path = Path("state/recall_last_run.json")
    default_k: int = 5
    reindex_threshold_minutes: int = 15
    skip_paths: list[str] = ["raw/elaborati"]
    embedder_health_check_timeout_seconds: int = 5
```

In `segretario.yaml.example` commentato:

```yaml
recall:
  # enabled: true
  # user_dismissed_wizard: false
  # embedding_model: "mxbai-embed-large"
  # default_k: 5
  # reindex_threshold_minutes: 15
```

**Importante per Task 3:** la flag `user_dismissed_wizard` sarà scritta nel
file di config quando l'utente sceglie "Non più chiedermelo". Task 3 dovrà
implementare la write atomica della config. In Task 2 prepariamo solo la
flag e la sua lettura.

## STEP 11 — `ReindexStateStore` + Job scheduler

`recall/state.py`: pattern identico a `BackupStateStore` di Task 1. File JSON
in `state/recall_last_run.json`:

```json
{
  "last_run": "2026-05-17T15:30:00+00:00",
  "indexed_count": 445,
  "embedding_model": "mxbai-embed-large"
}
```

Metodi `get_last_run()`, `set_last_run(when, indexed, model)`,
`should_skip(now, threshold_minutes)`.

Comportamento su file corrotto: log WARNING, ritorna None, procede.

Job in `src/segretario/scheduler/jobs.py`:

```python
{
    "name": "maintenance.recall_reindex",
    "command": "recall.reindex",
    "enabled": settings.recall.enabled,
}
```

Helper:

```python
def _run_recall_reindex(settings: Settings) -> str:
    if not settings.recall.enabled:
        return "recall.reindex: skipped: recall disabled in config"
    state = ReindexStateStore(settings.recall.state_path)
    now = datetime.now(timezone.utc)
    if state.should_skip(now, settings.recall.reindex_threshold_minutes):
        last = state.get_last_run()
        return f"recall.reindex: skipped: last run at {last.isoformat()}, threshold {settings.recall.reindex_threshold_minutes} min"
    # ... costruisci indexer e gira reindex ...
    result = indexer.reindex()
    state.set_last_run(now, result.indexed_total, settings.recall.embedding_model)
    return f"recall.reindex: indexed={result.indexed} deleted={result.deleted} skipped_unchanged={result.skipped_unchanged} errors={len(result.errors)}"
```

Pattern identico al `_run_vault_backup` di Task 1.

## STEP 12 — Integrazione con `ingest`

L'utente ha confermato che `il_segretario` ha ingest automatico probabilistico
("dado di probabilità") nel maintenance cycle. Quando una nota viene
effettivamente ingerita, l'indice deve aggiornarsi subito.

Trova tutti i punti di write con grep:

```powershell
Get-ChildItem -Path src/segretario -Recurse -Filter "*.py" | Select-String -Pattern "VaultTool.*write|MarkdownTool.*write|knowledge.*write_text" -List
```

Aggiungi come **ultimo step** dopo write riuscita:

```python
# Invalida l'indice recall per la nota appena scritta
if recall_settings.enabled:
    try:
        indexer.update_note(written_path)
    except Exception as exc:
        logger.warning("recall update_note failed for %s: %s. "
                       "Next scheduled reindex will catch up.", written_path, exc)
```

**CRITICO:** se `update_note` fallisce, l'ingest NON deve fallire. Ingest atomico, recall best-effort. Il prossimo reindex schedulato recupera drift.

Punti che probabilmente richiedono questa invalidazione:
- `ingest` CLI manuale
- ingest probabilistico nel maintenance cycle
- `link` → ingest pipeline
- `raw-to-knowledge`
- qualsiasi altro write a `knowledge/` o `output/`

Se trovi >3 callsite, refactorizza in helper/decorator (`@invalidates_recall(path_param="written_path")`).

## STEP 13 — CLI commands

```bash
uv run segretario recall reindex [--force]
uv run segretario recall reindex --dry-run
uv run segretario recall status
uv run segretario recall search "query" [--k 5]
uv run segretario recall reset-wizard   # rimette user_dismissed_wizard=False
```

Il comando `recall search` deve mostrare anche lo state e wizard_required del
`RecallResult` per debug, es:

```
$ uv run segretario recall search "ginocchio"
State: semantic_ready
Mode: semantic
Hits:
  knowledge/wellness-2025-09.md (score 0.847)
    "Visita per gonalgia bilaterale..."
  self/thoughts-2024-03.md (score 0.621)
    "Pensieri sul recupero post-infortunio..."
```

`recall reset-wizard`: riapre il wizard di attivazione. Utile per testing o
se l'utente cambia idea dopo "Non più chiedermelo". Setta
`user_dismissed_wizard=False` nella config via write atomica.

## STEP 14 — Test

Crea `tests/test_recall_*.py`. Test isolati con `tmp_path`, mai vault reale.

Test minimi (Claude Code aggiunge casi edge che vede necessari):

### Embedder
1. `test_embedder_embeds_text` — mock client, verifica 1024-dim output
2. `test_embedder_handles_ollama_down` — mock ConnectionError → `EmbedderError`
3. `test_embedder_health_check_true_when_ok` — mock embed success → True
4. `test_embedder_health_check_false_on_error` — mock ConnectionError → False

### Vector store
5. `test_sqlite_vec_store_upsert_and_query` — 3 vettori, query, top hit corretto
6. `test_sqlite_vec_store_upsert_idempotent` — doppio upsert, 1 record
7. `test_sqlite_vec_store_delete` — insert, delete, verifica assenza
8. `test_sqlite_vec_store_health_check` — connessione viva → True

### Indexer
9. `test_indexer_reindex_new_vault` — vault vuoto + 3 note → indexed=3
10. `test_indexer_reindex_skips_unchanged` — re-run → skipped_unchanged=3, indexed=0
11. `test_indexer_reindex_detects_modified` — modifica nota → re-indexed
12. `test_indexer_reindex_detects_deleted` — cancella → rimossa
13. `test_indexer_respects_skip_paths` — note in raw/elaborati non indicizzate
14. `test_indexer_indexes_self_directory` — note in self/ INDICIZZATE
15. `test_indexer_handles_single_note_embed_failure` — 1 nota fallisce, le altre ok, errors=[...]

### Retriever
16. `test_embedding_retriever_search_returns_top_k` — store con 10 note, k=3
17. `test_embedding_retriever_skips_missing_files` — hit a nota cancellata → log + skip

### State machine (cuore della logica nuova)
18. `test_state_machine_disabled_first_time` → `SEMANTIC_DISABLED_PROMPT` + WIZARD ACTIVATION
19. `test_state_machine_disabled_dismissed` → `SEMANTIC_DISABLED_DISMISSED`, no wizard
20. `test_state_machine_enabled_healthy` → `SEMANTIC_READY`, no wizard
21. `test_state_machine_enabled_embedder_down` → `SEMANTIC_UNAVAILABLE_TRANSIENT` + WIZARD DOWNGRADE
22. `test_state_machine_enabled_store_down` → `SEMANTIC_UNAVAILABLE_TRANSIENT` + WIZARD DOWNGRADE
23. `test_state_machine_override_keyword_once` → `SEMANTIC_DISABLED_OVERRIDE`, no wizard
24. `test_state_machine_override_keyword_proceed` → SEMANTIC_UNAVAILABLE_TRANSIENT, no wizard
25. `test_state_machine_wizard_context_activation_has_required_fields`
26. `test_state_machine_wizard_context_downgrade_has_failure_reason`

### RecallEngine facade
27. `test_recall_engine_returns_recall_result_when_enabled_and_healthy`
28. `test_recall_engine_returns_wizard_when_disabled_prompt`
29. `test_recall_engine_recall_simple_returns_none_when_wizard_required`
30. `test_recall_engine_recall_simple_returns_content_when_ready`
31. `test_recall_engine_keyword_search_explicit` — chiamata diretta a keyword_search
32. `test_recall_engine_backward_compat_no_settings` — vecchia inizializzazione, comportamento legacy

### State store
33. `test_reindex_state_store_skips_if_recent`
34. `test_reindex_state_store_corrupted_file_logs_and_proceeds`

### Scheduler
35. `test_scheduler_recall_reindex_job_respects_guard`
36. `test_scheduler_recall_reindex_job_skips_if_disabled`

### Ingest invalidation
37. `test_ingest_invalidates_recall_on_success`
38. `test_ingest_does_not_fail_if_recall_invalidation_fails`

Mock pattern: NON chiamare Ollama reale nei test. Usa `pytest-mock` o
`unittest.mock`. Path reale solo nello smoke test (STEP 16).

Verifica:

```powershell
uv run pytest tests/test_recall_*.py -v
uv run pytest -q
```

Atteso: 353 + ~38 = ~391 test verdi.

## STEP 15 — Documentazione

Aggiorna:

1. **`STATUS.md`** — nuova sezione "Recall semantico" sotto "Cosa è già
   implementato". Lista file, modello, comandi CLI, state machine 5-stati.
2. **`README.md`** — sezione "Comandi" aggiungi i nuovi `recall *`.
3. **`docs/secretary-flow02-decisions.md`** — aggiungi:

```markdown
## 9. Implementazione §8.2 (chiusa, 2026-05-17)

Recall L3 semantico implementato in Task 2. Decisioni di design:

- Approccio: Embeddings puro + architettura aperta a FTS5 futuro
- Modello: mxbai-embed-large (1024 dim) via Ollama locale
- Chunking: nota intera (coerente con LLM Wiki di Karpathy)
- Storage: sqlite-vec in database separato state/recall.sqlite
- Pre-filtering privacy: nessuno (self/ indicizzato, privacy = broker downstream)
- Re-indexing: scheduled (skip < 15 min) + invalidazione su ingest
- State machine a 5 stati per gestire i casi reali:
  SEMANTIC_READY, SEMANTIC_DISABLED_PROMPT (wizard A),
  SEMANTIC_DISABLED_DISMISSED, SEMANTIC_UNAVAILABLE_TRANSIENT (wizard B),
  SEMANTIC_DISABLED_OVERRIDE (per-turno)

## 10. Nota di design — variante doppio broker (futura)

[testo come da STEP 17 sotto]

## 11. TODO — Design distribuzione il_segretario + zarsOS

Domanda aperta: come distribuire `il_segretario` insieme a zarsOS?
Tre alternative discusse:
- A. Monorepo unico (un installer per entrambi)
- B. zarsOS standalone + il_segretario plug-in opzionale
- C. il_segretario embedded come dipendenza Python managed da zarsOS Node

Decisione: rivedere durante o dopo Task 4 (integrazione HTTP), quando
avremo visto come i due dialogano in pratica.
```

4. **`docs/recall-future-work.md`** (file nuovo): contiene la nota
   doppio broker (STEP 16) + ogni follow-up emerso durante implementazione.

## STEP 16 — Nota di design "doppio broker"

In `docs/recall-future-work.md`:

```markdown
# Recall L3 — Future work

## Variante doppio broker (futura, non implementata)

Il design corrente affida la privacy projection a un singolo broker
(`ContextBroker`). I vettori indicizzati includono anche contenuti da
`self/` perché la decisione architetturale §3.6 (2026-05-15) stabilisce
che la privacy sta nel *come* si proietta, non nel *cosa* si recupera.

In futuro si potrebbe valutare l'introduzione di un *secondo* broker
indipendente posto a valle del primo, con regole leggermente diverse,
come difesa in profondità contro bug del primo broker. Pattern "belt and
suspenders": se il primo broker ha un bug e non maschera qualcosa, il
secondo (indipendente per implementazione) ha una chance di intercettarlo.

Variante a due broker ≠ pre-filtering nell'indice. Il principio §3.6
resta valido: la privacy non limita il volume del retrieval, ma garantisce
la proiezione.

Decisione: rivalutare quando il sistema sarà in produzione attiva e ci
saranno dati reali sui pattern di failure del primo broker.

## TODO — FTS5 come secondo retriever

Architettura aperta: l'interfaccia `Retriever` permette di aggiungere
FTS5 come secondo retriever da fondere con `EmbeddingRetriever` via
Reciprocal Rank Fusion. Da valutare se i match keyword puri mancano
(es. nomi propri, codici, sigle) sull'esperienza reale.
```

## STEP 17 — Smoke test reale (manuale)

DOPO che i test sono verdi. NON automatizzare. Esegui manualmente e
riporta nel summary.

```powershell
# 1. Abilita recall in segretario.yaml (aggiungi: recall: enabled: true)

# 2. Primo reindex completo (atteso 5-10 min su 445 note)
uv run segretario recall reindex

# 3. Verifica stato
uv run segretario recall status

# 4. Query di test
uv run segretario recall search "test query" --k 3

# 5. Re-reindex immediato (deve skippare per guardia 15 min)
uv run segretario recall reindex

# 6. Scheduler run-once
uv run segretario scheduler run-once --execute

# 7. Disabilita recall (recall: enabled: false), prova recall search
# Atteso: stato "SEMANTIC_DISABLED_PROMPT", wizard ACTIVATION info
uv run segretario recall search "test query"

# 8. Riabilita e test query reale con risultati
```

Atteso:
- Step 2: ~445 note indicizzate in ~5-10 min, stato "ok"
- Step 3: report con count, modello, ultimo run
- Step 4: 3 hits con score, paths reali
- Step 5: "skipped: last run at ..., threshold 15 min"
- Step 6: anche recall.reindex skip
- Step 7: stato SEMANTIC_DISABLED_PROMPT con wizard_context popolato
- Step 8: query semantica funziona

Riporta output esatto di ogni step. Se qualcosa fallisce, NON committare:
ferma e segnala.

## STEP 18 — Commit e summary finale

Commit message:

```
feat(recall): semantic L3 with 5-state machine + sqlite-vec

- New module src/segretario/recall/ with Retriever/VectorStore protocols
- Embedding-based retrieval (mxbai-embed-large, 1024 dim) via Ollama
- sqlite-vec storage at state/recall.sqlite (separate from taskboard)
- 5-state machine: READY / DISABLED_PROMPT / DISABLED_DISMISSED /
  UNAVAILABLE_TRANSIENT / DISABLED_OVERRIDE
- Wizard data exposed but UI deferred to Task 3
- Scheduled reindex (15-min guard) + ingest invalidation
- RecallEngine facade: new recall() returns RecallResult, recall_simple()
  preserves legacy str|None API for backward compat
- Keyword stub extracted to keyword_search.py, used explicitly (not auto-fallback)
- self/ NOT pre-filtered (privacy delegated to ContextBroker per §3.6)
- 38 new tests, all green; full suite still green
- Manual smoke test on real vault: 445 notes indexed in X min

Closes Task 2 of il_segretario completion plan.
Next: Task 3 (wizard UX in zarsOS).
Backup pre-implementation: il_segretario_vault_manual_<TS>.zip
```

Summary finale deve includere:
1. Backup pre-implementation: path, size, sha256
2. Lista file nuovi creati (con righe ciascuno)
3. Lista file modificati
4. Lista callsite di `RecallEngine.recall()` aggiornati e come (recall_simple vs recall)
5. Output `uv run pytest -q` finale
6. Output completo smoke test (STEP 17), inclusi step 7 e 8 sul wizard
7. Eventuali deviazioni dal piano e perché
8. Commit hash

## Cosa NON fare

- NON cambiare il `flow02/recall_engine.py` path. Resta lì come facade.
- NON includere `meta/privacy_map.local.json` nell'indice (no-export).
- NON pre-filtrare `self/` (decisione esplicita).
- NON aggiungere fallback automatico al keyword quando `enabled=False`. Il
  keyword è invocato esplicitamente solo dai code path che lo richiedono.
- NON implementare i wizard veri (UI). Solo espone i dati per Task 3.
- NON aggiungere FTS5 oggi.
- NON automatizzare lo smoke test.
- NON committare se smoke test o suite non sono entrambi verdi.
- NON modificare il `ContextBroker` oltre lo stretto necessario per usare
  `recall_simple()` invece di `recall()` (mantieni il comportamento).

## Stop and ask

Fermati se trovi:
- Backup pre-implementation fallisce
- `sqlite-vec` problemi su Windows + Python 3.11
- Client Python `ollama` non disponibile o versione incompatibile
- L'API API `RecallEngine.recall()` è usata in modi che non puoi preservare con la facade
- `ContextBroker` ha struttura troppo intricata per il refactor minimale
- Schema sqlite-vec problemi con `load_extension`
- Indicizzazione real-world fallisce su >10% delle note
- Reindex eccede budget 10 min del maintenance cycle
- `RecallResult` causa breaking change in chiamanti che non riesci a gestire
- Smoke test step 7/8 (wizard data) ritorna stato/context inattesi

## Skills

Sono installate localmente diverse skills (superpower, get-shit-done, ecc.).
Caricale e usale se rilevanti per questo task. Sei autonomo nel decidere
quali applicare.

## Stato a fine Task 2

Task 2 è chiuso quando:
- Backup pre-implementation esiste e verificato
- Tutti i file nuovi creati seguono l'architettura sopra
- ~38 nuovi test verdi, suite completa zero regressioni
- Smoke test reale completato con successo, inclusi step su wizard data
- Documentazione aggiornata (STATUS, README, decisions, recall-future-work)
- Commit pulito su master
- Summary finale presentato

**Prossimo task dopo questo è Task 3** (wizard UX in zarsOS), che userà i
dati di `RecallResult.wizard_required` e `wizard_context` esposti qui.
