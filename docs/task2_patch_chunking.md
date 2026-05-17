# Claude Code — Task 2 Patch: Chunking H2 + overlap

## Contesto

Stiamo nel worktree `e:\il_segretario\.worktrees\task2-recall-semantic`,
branch già attivo. **NON committare niente di Task 2 finora.** Lo smoke test
ha rivelato un problema bloccante.

## Il problema scoperto allo smoke test

Il reindex sul vault reale ha indicizzato **solo 105 note su 445** (23%).
340 note hanno fallito con due errori principali:

1. **~337 errori**: `Ollama model error: the input length exceeds the context length (status code: 400)`
2. **~3 errori**: `Ollama returned empty embedding response` su file specifici
   (`Austinitered.md`, `Fluffy_WAR_Bunny.md`, `fapyshop.com.md`)

**Root cause del problema 1:** `mxbai-embed-large` ha context window di
**512 token** (`bert.context_length: 512` nel modelfile), non 8192 come
assunto inizialmente. L'endpoint Ollama `/api/embed` tronca a 512 token
indipendentemente dal `num_ctx` configurato. 512 token in italiano corrispondono
a ~1400-1600 caratteri, non gli 8000 che avevamo nel design originale di Task 2.

Il design "whole-note chunking" era basato su assunzione sbagliata sul
context window. Il vault ha decine di note tra 8000 e 320000 caratteri.

## Cosa NON fare

- NON cambiare modello (mxbai resta).
- NON committare niente di Task 2 finora.
- NON toccare la state machine, embedder client, vector store, retriever,
  scheduler, CLI, RecallEngine facade. **Funzionano.** Lo smoke test l'ha
  confermato.
- NON toccare il database schema esistente OLTRE ai cambi descritti sotto.
- NON gestire le 3 note "empty response" ora. Resta TODO follow-up. Logga
  errore e prosegui come fa adesso.

## Cosa fare

Modifica chirurgica al chunking. Tutto il resto del modulo `recall/` resta com'è.

## Decisioni di design (già prese, NON re-discutere)

1. **Strategia chunking:** Note con `## ` (H2) → un chunk per sezione H2.
   Note senza H2 → un chunk se ≤1500 char, splittate in chunk di ~1500 char
   con overlap di 200 char se lunghe.
2. **Sezioni H2 lunghe:** se una sezione H2 supera 1500 char, viene splittata
   internamente con stessa logica (chunk ~1500 char + overlap 200 char).
3. **Overlap obbligatorio in tutti gli split:** anche tra sezioni H2 consecutive,
   gli ultimi 200 char della sezione precedente vengono prepended all'inizio
   della successiva. Esempio: se sezione `## A` finisce con "...preparare il
   contesto" e sezione `## B` inizia con "Per implementare...", il chunk di
   `## B` includerà gli ultimi 200 char di `## A` come prefisso.
4. **Target chunk size:** 1500 caratteri (sicuro per italiano su context window
   512 token mxbai).
5. **RecallHit ora rappresenta un chunk, non una nota.** Aggiungere campi
   `chunk_index` e `section_title` (se disponibile, altrimenti None).

## STEP 1 — Aggiornare `models.py`

In `src/segretario/recall/models.py`, modifica `RecallHit`:

```python
@dataclass
class RecallHit:
    """Singolo match restituito dal retriever. Rappresenta un chunk di una nota."""
    note_path: str            # path relativo della nota
    chunk_index: int          # 0-based index del chunk nella nota
    section_title: str | None # titolo H2 della sezione, se applicabile
    score: float
    content_preview: str      # primi 500 char del chunk
```

Aggiungi dataclass nuova `Chunk` se non già esistente:

```python
@dataclass
class Chunk:
    """Risultato dello splitting di una nota."""
    note_path: str
    chunk_index: int            # 0-based
    section_title: str | None   # H2 title se disponibile, altrimenti None
    content: str                # testo del chunk (con eventuale prefix di overlap)
    char_count: int             # len(content), per debug
```

## STEP 2 — Sostituire `chunker.py`

Il file `src/segretario/recall/chunker.py` attualmente contiene
`WholeNoteChunker`. Sostituiscilo con `H2OverlapChunker`:

```python
from __future__ import annotations
import re
from typing import Iterator

from segretario.recall.models import Chunk


CHUNK_TARGET_SIZE = 1500
CHUNK_OVERLAP_SIZE = 200

H2_PATTERN = re.compile(r'^##\s+(.+?)\s*$', re.MULTILINE)


class H2OverlapChunker:
    """Chunker che divide note per sezioni H2 con overlap.

    Logica:
    - Note senza H2 e ≤ CHUNK_TARGET_SIZE: 1 chunk = nota intera
    - Note senza H2 e > CHUNK_TARGET_SIZE: split per blocchi di ~CHUNK_TARGET_SIZE
      con overlap di CHUNK_OVERLAP_SIZE
    - Note con H2: ogni sezione H2 è un chunk (preceduta da overlap della sezione
      precedente). Se una sezione supera CHUNK_TARGET_SIZE, viene a sua volta
      splittata internamente con stessa logica.
    """

    def chunk(self, note_path: str, content: str) -> list[Chunk]:
        """Divide il contenuto della nota in chunks.

        :param note_path: path relativo della nota (per metadati)
        :param content: testo completo della nota
        :returns: lista di Chunk pronti per embedding
        """
        if not content.strip():
            return []

        sections = self._split_by_h2(content)

        if not sections:
            # Nota senza H2: applica split senza section_title
            return self._chunk_plain_text(note_path, content, section_title=None)

        # Nota con H2: chunka sezione per sezione con overlap inter-sezione
        chunks: list[Chunk] = []
        previous_tail = ""

        for section_title, section_content in sections:
            # Aggiungi overlap dalla sezione precedente
            content_with_overlap = (previous_tail + section_content).strip()
            section_chunks = self._chunk_plain_text(
                note_path,
                content_with_overlap,
                section_title=section_title,
                start_index=len(chunks),
            )
            chunks.extend(section_chunks)
            previous_tail = section_content[-CHUNK_OVERLAP_SIZE:] if len(section_content) > CHUNK_OVERLAP_SIZE else section_content

        return chunks

    def _split_by_h2(self, content: str) -> list[tuple[str, str]]:
        """Splitta il contenuto in (titolo_h2, contenuto_sezione).

        La parte di testo PRIMA del primo H2 (preamble) viene attaccata alla
        prima sezione. Se non ci sono H2, ritorna lista vuota.
        """
        matches = list(H2_PATTERN.finditer(content))
        if not matches:
            return []

        sections: list[tuple[str, str]] = []
        preamble = content[:matches[0].start()].strip()

        for i, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_content = content[start:end].strip()
            # Per la prima sezione, includi il preamble se esiste
            if i == 0 and preamble:
                section_content = preamble + "\n\n" + section_content
            sections.append((title, section_content))

        return sections

    def _chunk_plain_text(
        self,
        note_path: str,
        text: str,
        section_title: str | None,
        start_index: int = 0,
    ) -> list[Chunk]:
        """Splitta plain text in chunks di ~CHUNK_TARGET_SIZE con overlap."""
        if not text.strip():
            return []

        if len(text) <= CHUNK_TARGET_SIZE:
            return [Chunk(
                note_path=note_path,
                chunk_index=start_index,
                section_title=section_title,
                content=text,
                char_count=len(text),
            )]

        chunks: list[Chunk] = []
        idx = start_index
        pos = 0

        while pos < len(text):
            end = min(pos + CHUNK_TARGET_SIZE, len(text))
            chunk_content = text[pos:end]
            chunks.append(Chunk(
                note_path=note_path,
                chunk_index=idx,
                section_title=section_title,
                content=chunk_content,
                char_count=len(chunk_content),
            ))
            idx += 1
            if end >= len(text):
                break
            pos = end - CHUNK_OVERLAP_SIZE

        return chunks
```

**Casi edge da gestire nei test (vedi STEP 5):**
- Nota vuota o solo whitespace → lista vuota
- Nota di 1 carattere → 1 chunk
- Nota esattamente 1500 char → 1 chunk
- Nota 1501 char → 2 chunk (secondo con overlap)
- Nota con H2 ma sezione vuota → skip sezione vuota
- Nota che inizia con H2 (no preamble) → ok
- Nota con preamble + H2 → preamble attaccato a prima sezione

## STEP 3 — Aggiornare schema sqlite-vec

Lo schema attuale ha `indexed_notes` con primary key `path`. Ora servono
*chunk* invece di *note* come unità indicizzata. Modifiche:

```sql
-- Modifica schema: traccia chunk per chunk
DROP TABLE IF EXISTS indexed_notes;
CREATE TABLE IF NOT EXISTS indexed_chunks (
    note_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    section_title TEXT,             -- NULL se nota senza H2
    content_hash TEXT NOT NULL,     -- hash del CONTENT del chunk, non della nota
    note_hash TEXT NOT NULL,        -- hash della nota intera (per detect changes)
    indexed_at TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    PRIMARY KEY (note_path, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_note_path ON indexed_chunks(note_path);
CREATE INDEX IF NOT EXISTS idx_chunks_note_hash ON indexed_chunks(note_hash);

-- Vector table: una riga per chunk, non per nota
DROP TABLE IF EXISTS note_vectors;
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
    note_path TEXT,
    chunk_index INTEGER,
    embedding FLOAT[1024]
);
```

**ATTENZIONE — Migrazione:** lo smoke test ha già scritto dati con lo schema
vecchio. Hai due alternative:

- **Alternativa A (consigliata):** drop totale del database recall. Lo
  smoke test ha indicizzato solo 105 note che sono comunque inutili da
  riusare perché 340 mancanti. Conviene ripartire.

  ```python
  # All'avvio del SqliteVecStore, se vede tabelle vecchie incompatibili,
  # esegue drop e ricrea da zero. Logga WARNING.
  ```

  Implementazione: controllo `PRAGMA table_info(indexed_notes)` e se esiste
  vecchio schema, drop + ricrea.

- **Alternativa B:** migrazione esplicita con `ALTER TABLE`. Più complesso,
  zero valore aggiunto per il tuo caso (sei in worktree, vuoi solo ripartire).

**Usa Alternativa A.** Logga chiaramente nel terminale quando ricrei lo schema.

## STEP 4 — Aggiornare `SqliteVecStore`

Adatta i metodi al nuovo schema:

```python
class VectorStore(Protocol):
    def upsert_chunk(
        self,
        note_path: str,
        chunk_index: int,
        section_title: str | None,
        embedding: list[float],
        content_hash: str,
        note_hash: str,
    ) -> None: ...

    def delete_note(self, note_path: str) -> None:
        """Cancella TUTTI i chunk di una nota."""

    def query(self, embedding: list[float], k: int = 5) -> list[VectorHit]:
        """Ritorna chunk_vectors join indexed_chunks per avere section_title."""

    def get_indexed_note_hash(self, note_path: str) -> str | None:
        """Ritorna il note_hash di una nota indicizzata (per detect changes).
        None se la nota non è indicizzata."""

    def list_indexed_paths(self) -> set[str]:
        """Set di note_path con almeno un chunk indicizzato."""
```

`VectorHit` deve includere `chunk_index` e `section_title`:

```python
@dataclass
class VectorHit:
    note_path: str
    chunk_index: int
    section_title: str | None
    score: float
```

## STEP 5 — Aggiornare `VaultIndexer`

In `indexer.py`:

```python
def _index_note(self, note_path: Path, content: str) -> None:
    """Indicizza una nota: chunka, embedda ogni chunk, upserta."""
    chunks = self._chunker.chunk(str(note_path), content)
    if not chunks:
        logger.warning("Note %s produced no chunks (empty/whitespace)", note_path)
        return

    note_hash = sha256(content.encode("utf-8")).hexdigest()

    # Prima cancella eventuali vecchi chunk di questa nota
    self._store.delete_note(str(note_path))

    for chunk in chunks:
        try:
            embedding = self._embedder.embed(chunk.content)
            content_hash = sha256(chunk.content.encode("utf-8")).hexdigest()
            self._store.upsert_chunk(
                note_path=chunk.note_path,
                chunk_index=chunk.chunk_index,
                section_title=chunk.section_title,
                embedding=embedding,
                content_hash=content_hash,
                note_hash=note_hash,
            )
        except EmbedderError as exc:
            logger.error(
                "Failed to embed chunk %d of %s: %s",
                chunk.chunk_index,
                note_path,
                exc,
            )
            # Continua con i prossimi chunk: meglio indicizzare parzialmente che niente
```

Il diff per `reindex()` ora usa `note_hash` invece di `content_hash`:

```python
def reindex(self, force: bool = False) -> ReindexResult:
    indexed = 0
    skipped_unchanged = 0
    deleted = 0
    errors: list[str] = []

    fs_paths = set(self._scan_vault())
    indexed_paths = self._store.list_indexed_paths()

    for path in fs_paths:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue

        current_note_hash = sha256(content.encode("utf-8")).hexdigest()
        stored_hash = self._store.get_indexed_note_hash(str(path.relative_to(self._vault_path)))

        if not force and stored_hash == current_note_hash:
            skipped_unchanged += 1
            continue

        try:
            self._index_note(path.relative_to(self._vault_path), content)
            indexed += 1
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    # Cancella note non più presenti sul filesystem
    fs_relative_paths = {str(p.relative_to(self._vault_path)) for p in fs_paths}
    stale = indexed_paths - fs_relative_paths
    for stale_path in stale:
        self._store.delete_note(stale_path)
        deleted += 1

    return ReindexResult(
        indexed=indexed,
        deleted=deleted,
        skipped_unchanged=skipped_unchanged,
        errors=errors,
    )
```

## STEP 6 — Aggiornare `EmbeddingRetriever`

```python
def search(self, query: str, k: int = 5) -> list[RecallHit]:
    query_embedding = self._embedder.embed(query)
    vec_hits = self._store.query(query_embedding, k=k)
    return [self._enrich(hit) for hit in vec_hits if self._note_exists(hit)]

def _enrich(self, vec_hit: VectorHit) -> RecallHit:
    """Costruisce RecallHit leggendo il content_preview dal chunk corrispondente."""
    # Per il preview, leggi la nota e ri-chunka per estrarre il chunk N.
    # Alternativa più efficiente: salvare il content del chunk anche nel DB.
    # Per semplicità V1, ri-chunka.
    note_full_path = self._vault_path / vec_hit.note_path
    if not note_full_path.exists():
        return None  # gestito dal caller
    content = note_full_path.read_text(encoding="utf-8", errors="replace")
    chunks = self._chunker.chunk(vec_hit.note_path, content)
    if vec_hit.chunk_index >= len(chunks):
        # Drift: l'indice ha più chunks di quanti la nota produce ora
        logger.warning("Chunk drift on %s: index %d not in current chunking", vec_hit.note_path, vec_hit.chunk_index)
        return None
    chunk = chunks[vec_hit.chunk_index]
    return RecallHit(
        note_path=vec_hit.note_path,
        chunk_index=vec_hit.chunk_index,
        section_title=vec_hit.section_title,
        score=vec_hit.score,
        content_preview=chunk.content[:500],
    )
```

**Nota di ottimizzazione futura:** ri-leggere e ri-chunkare la nota a ogni
search è inefficiente. Una v2 potrebbe salvare il chunk content nel DB (è
piccolo, ~1500 char per chunk). Lascialo come TODO nel docstring; v1 fa
così.

## STEP 7 — CLI `recall search`

Aggiorna l'output di `recall search` per mostrare il section_title quando
disponibile:

```
$ uv run segretario recall search "react state"
State:  semantic_ready
Mode:   semantic
Hits:
  knowledge/react-hooks.md [§ Managing Component State] (chunk 2, score 0.821)
    "Per gestire lo stato locale di un componente, useState è il hook..."
  knowledge/react-patterns.md [§ Lifting State Up] (chunk 0, score 0.764)
    "Quando più componenti condividono dati..."
  raw/extracted/react-state-coursera.md (chunk 1, score 0.701)
    "Lo stato in React è il modo in cui..."
```

Formato:
- Se `section_title` presente: `path/to/note.md [§ Section Title] (chunk N, score X.XXX)`
- Se `section_title` None (nota senza H2): `path/to/note.md (chunk N, score X.XXX)`

## STEP 8 — Test

Aggiungi questi test in `tests/test_recall_chunker.py` (file nuovo):

```python
def test_chunker_empty_note():
    chunker = H2OverlapChunker()
    assert chunker.chunk("test.md", "") == []
    assert chunker.chunk("test.md", "   \n  \n") == []

def test_chunker_short_note_no_h2():
    chunker = H2OverlapChunker()
    chunks = chunker.chunk("test.md", "Una breve nota.")
    assert len(chunks) == 1
    assert chunks[0].content == "Una breve nota."
    assert chunks[0].section_title is None
    assert chunks[0].chunk_index == 0

def test_chunker_long_note_no_h2_splits_with_overlap():
    chunker = H2OverlapChunker()
    content = "A" * 3500  # 3500 chars
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 3  # 1500 + 1500 (with 200 overlap) + 500 (with 200 overlap)
    assert all(c.section_title is None for c in chunks)
    # Overlap check: chunk[1] inizia con overlap di chunk[0]
    # ATTENZIONE: con il pattern (pos = end - OVERLAP), chunk[1][:200] == chunk[0][-200:]
    assert chunks[1].content[:200] == chunks[0].content[-200:]

def test_chunker_note_with_h2_sections():
    chunker = H2OverlapChunker()
    content = "## Sezione A\nContenuto A.\n\n## Sezione B\nContenuto B."
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 2
    assert chunks[0].section_title == "Sezione A"
    assert chunks[1].section_title == "Sezione B"

def test_chunker_h2_section_overlap_between_sections():
    chunker = H2OverlapChunker()
    # Sezione A finisce con testo distintivo che deve apparire all'inizio di B
    content = (
        "## Sezione A\n" + "Z" * 500 + "FINEUNICA"
        + "\n\n## Sezione B\n" + "Contenuto B normale."
    )
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 2
    assert chunks[1].section_title == "Sezione B"
    # B deve contenere overlap di A
    assert "FINEUNICA" in chunks[1].content

def test_chunker_preamble_attached_to_first_h2():
    chunker = H2OverlapChunker()
    content = "Preambolo iniziale.\n\n## Prima sezione\nContenuto."
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 1
    assert chunks[0].section_title == "Prima sezione"
    assert "Preambolo iniziale" in chunks[0].content

def test_chunker_long_h2_section_gets_subsplit():
    chunker = H2OverlapChunker()
    content = "## Sezione lunga\n" + "X" * 3500
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) >= 3  # sezione di 3500 char + heading viene splittata
    assert all(c.section_title == "Sezione lunga" for c in chunks)
    # I chunk consecutivi devono avere overlap
    assert chunks[1].content[:200] == chunks[0].content[-200:]

def test_chunker_exact_1500_chars():
    chunker = H2OverlapChunker()
    content = "B" * 1500
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 1

def test_chunker_1501_chars_produces_two_chunks():
    chunker = H2OverlapChunker()
    content = "C" * 1501
    chunks = chunker.chunk("test.md", content)
    assert len(chunks) == 2

def test_chunker_h2_with_empty_section_skipped():
    chunker = H2OverlapChunker()
    content = "## Vuota\n\n## Piena\nContenuto."
    chunks = chunker.chunk("test.md", content)
    # Sezione vuota produce 0 chunk; sezione piena produce 1.
    # Verifica: solo "Piena" presente nei risultati.
    section_titles = [c.section_title for c in chunks]
    assert "Piena" in section_titles
    # Implementazione: la sezione "Vuota" passa per _chunk_plain_text con
    # text vuoto → ritorna []. Quindi non appare. Verifica.
```

Aggiungi anche test di integrazione in `tests/test_recall_indexer.py`:

```python
def test_indexer_chunks_long_note():
    """Una nota lunga viene indicizzata come N chunks, non come 1."""
    # Setup: crea nota di 5000 char
    # Esegui indexer
    # Verifica che store contenga N chunks per quella nota
    # Verifica che list_indexed_paths ritorni 1 path (non N)

def test_indexer_updates_chunks_on_note_change():
    """Modificare una nota cancella vecchi chunk e crea nuovi."""

def test_indexer_chunk_failure_does_not_block_other_chunks():
    """Se un chunk fallisce embed, gli altri chunk della nota vengono comunque indicizzati."""

def test_retriever_returns_section_title_when_present():
    """RecallHit ha section_title popolato per match in sezioni H2."""

def test_retriever_returns_none_section_for_h2less_note():
    """RecallHit ha section_title=None per match in note senza H2."""
```

Sicuramente serve aggiornare anche i test esistenti che usavano il vecchio
`WholeNoteChunker` o assumevano `RecallHit` senza `chunk_index`/`section_title`.

## STEP 9 — Smoke test reale

DOPO i test verdi:

```powershell
cd e:\il_segretario\.worktrees\task2-recall-semantic

# 1. (Opzionale ma raccomandato) cancella DB vecchio per ripartire pulito
Remove-Item state\recall.sqlite -Force -ErrorAction SilentlyContinue
Remove-Item state\recall_last_run.json -Force -ErrorAction SilentlyContinue

# 2. Reindex completo
uv run segretario recall reindex
# ATTESO:
# - indexed >= 442 (sui 445 totali, le 3 "empty response" potrebbero ancora fallire)
# - errors ≤ 5 (ideale 3: solo le 3 file problematici)
# - tempo: ~20-30 minuti per ~700-1000 chunks (più chunks delle 445 note originali)

# 3. Status
uv run segretario recall status

# 4. Query reali di test
uv run segretario recall search "react state management" --k 3
uv run segretario recall search "data analysis coursera" --k 5
uv run segretario recall search "zarsos privacy projection" --k 3

# 5. Verifica skip
uv run segretario recall reindex
# ATTESO: "skipped: last run at ... threshold 15 min"

# 6. Test wizard activation (disabilita recall, prova)
# (Modifica segretario.yaml: recall.enabled: false)
uv run segretario recall search "test"
# ATTESO: State semantic_disabled_prompt + Wizard activation

# 7. Riabilita
```

**Criteri di successo dello smoke test:**

- `indexed=442+` (vs 105 attuali, miglioramento 4x)
- `errors=3-5` (solo le 3 note "empty response" + eventuale 1-2 altre)
- Almeno una query restituisce hit con `score > 0.5` (vs gli 0.23-0.46 attuali)
- Almeno una query restituisce hit con `section_title` popolato (dimostra che chunking H2 funziona)
- Tutti gli stati della state machine continuano a funzionare come prima

Riporta nel summary l'output completo di ogni passo.

## STEP 10 — Documentazione

Aggiorna in `docs/secretary-flow02-decisions.md` la sezione §9
(Implementazione §8.2):

```markdown
## 9. Implementazione §8.2 (chiusa, 2026-05-17)

Recall L3 semantico implementato in Task 2.

Decisioni di design finali (dopo correzione chunking post-smoke-test):

- Approccio: Embeddings puro + architettura aperta a FTS5 futuro
- Modello: mxbai-embed-large (1024 dim, context window 512 token) via Ollama
- **Chunking: H2 sections con overlap 200 char + fallback split per note senza H2.**
  Target chunk 1500 char (sicuro per 512-token context su italiano).
- Storage: sqlite-vec in database separato state/recall.sqlite
- Schema: chunk-based (indexed_chunks + chunk_vectors)
- Pre-filtering privacy: nessuno (self/ indicizzato, privacy = broker downstream)
- Re-indexing: scheduled (skip < 15 min) + invalidazione su ingest
- State machine a 5 stati: SEMANTIC_READY, SEMANTIC_DISABLED_PROMPT (wizard A),
  SEMANTIC_DISABLED_DISMISSED, SEMANTIC_UNAVAILABLE_TRANSIENT (wizard B),
  SEMANTIC_DISABLED_OVERRIDE

### Note storiche

Il design iniziale del 2026-05-17 prevedeva "whole-note chunking" basato su
assunzione errata che mxbai-embed-large avesse context window 8192 token.
Lo smoke test ha rivelato il limite reale 512 token (~1500 char italiano):
solo 23% del vault si indicizzava. La correzione è stata applicata lo stesso
giorno con strategia chunking H2 + overlap.
```

E in `docs/recall-future-work.md`, aggiungi:

```markdown
## TODO — Ottimizzazioni chunking

1. **Salvare chunk content nel DB invece di ri-chunkare a search time.**
   La V1 ri-legge e ri-chunka la nota a ogni query. Salvare il content nel DB
   (campo TEXT in indexed_chunks) elimina I/O e ri-computation, al costo di
   ~1.5 KB per chunk di storage extra.

2. **Investigare le 3 note "empty response" da Ollama.**
   `Austinitered.md`, `Fluffy_WAR_Bunny.md`, `fapyshop.com.md` ritornano embedding
   vuoto da Ollama. Ipotesi: file vuoti, solo whitespace/unicode strani, o bug
   Ollama specifico. Indagare contenuto e correggere caso per caso.

3. **Chunking adattivo per code blocks e tabelle.**
   Markdown con code fences (```) o tabelle pesanti possono produrre chunk
   in cui la struttura viene rotta a metà. V2 potrebbe rilevare ed evitare
   split dentro code blocks o tabelle.
```

## STEP 11 — Commit

**SOLO se** lo smoke test passa i criteri di successo:

```
feat(recall): H2 chunking with overlap to fit mxbai 512-token context window

Fixes critical issue discovered in Task 2 smoke test: mxbai-embed-large has
context window of 512 tokens (~1500 char Italian), not 8192 as initially
assumed. Whole-note chunking caused 340/445 notes to fail indexing.

Changes:
- New H2OverlapChunker in src/segretario/recall/chunker.py
- Schema migration: indexed_notes → indexed_chunks, note_vectors → chunk_vectors
- RecallHit now includes chunk_index and section_title
- VectorStore protocol updated to chunk-aware methods
- Indexer chunks each note, embeds and upserts per chunk
- EmbeddingRetriever re-chunks at search time to provide content_preview
- CLI `recall search` shows section_title when present
- N new tests for chunker, M updated tests for indexer/retriever
- Manual smoke test on real vault: 442+/445 notes indexed

Closes Task 2 of il_segretario completion plan.
Backup pre-implementation: il_segretario_vault_manual_<TS>.zip (from earlier today)
```

Summary finale deve includere:

1. Lista file modificati con righe ciascuno
2. Output completo nuovi test
3. Output `uv run pytest -q` finale
4. Output smoke test completo (STEP 9)
5. Conferma criteri successo soddisfatti (indexed=?, errors=?, score max=?)
6. Commit hash
7. Note di follow-up emerse (tra cui le 3 note empty response)

## Stop and ask

Fermati se:

- Lo smoke test produce ancora >10% di errori dopo chunking (significa che il
  chunking ha bug o ci sono note con caratteri patologici).
- I test mostrano comportamenti inattesi del chunker (es. infinite loop su
  edge case).
- Schema migration fallisce con dati esistenti (l'Alternativa A drop dovrebbe
  evitare il problema).
- Le 3 note "empty response" diventano >10 (significa pattern più ampio).
- Lo score top per query reali resta sotto 0.5 anche con chunking (significa
  che il problema è in altro: query formulation, modello, ecc.).
- Performance reindex >30 min (sospetto bug nel loop di embedding).

## Stato a fine Task 2 (vero finale)

Task 2 è chiuso quando:

- Chunker H2 implementato e testato
- Schema sqlite-vec aggiornato a chunk-based
- Tutti i test verdi (esistenti + nuovi)
- Smoke test reale soddisfa criteri di successo (indexed 442+, score >0.5)
- Documentazione aggiornata con note storiche sul cambio chunking
- Commit pulito su branch task2 nel worktree
- Summary completo presentato
