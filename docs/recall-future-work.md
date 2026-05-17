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

## TODO — Chunking per note lunghe

Il design attuale usa whole-note chunking (una nota = un vettore).
Per note molto lunghe (>2000 token), la qualità dell'embedding può
degradare. Valutare sliding-window chunking in futuro.
