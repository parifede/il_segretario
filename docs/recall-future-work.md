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

## TODO — Ottimizzazioni chunking

1. **Salvare chunk content nel DB invece di ri-chunkare a search time.**
   La V1 ri-legge e ri-chunka la nota a ogni query per generare il preview.
   Salvare il content nel DB (campo TEXT in `indexed_chunks`) elimina I/O
   e ri-computation, al costo di ~1.5 KB per chunk di storage extra.

2. **Investigare le note con "empty response" da Ollama.**
   Alcune note (`Austinitered.md`, `Fluffy_WAR_Bunny.md`, `fapyshop.com.md`)
   ritornano embedding vuoto da Ollama. Ipotesi: contenuto non-testuale,
   solo whitespace/unicode, o bug specifico Ollama. Indagare e correggere.

3. **Chunk di URL/wikilink sovra-size (~100 nel vault attuale).**
   Alcuni chunk superano i 1500 char per via di sezioni H2 con liste dense
   di wikilink o URL lunghi. Il chunker li subsplit ma i chunk risultanti
   possono avere struttura degradata. V2 potrebbe rilevare ed evitare split
   dentro liste di link consecutive.

4. **Chunking adattivo per code blocks e tabelle.**
   Markdown con code fences (``` ```) o tabelle pesanti possono produrre chunk
   in cui la struttura viene rotta a metà. V2 potrebbe rilevare ed evitare
   split dentro code blocks o tabelle.
