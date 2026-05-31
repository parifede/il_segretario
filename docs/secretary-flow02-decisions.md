# Segretario — Decisioni di design Flow 02 e Retry Loop

> Documento di riferimento delle decisioni prese in chat il 2026-05-15.
> Scope: integrazione e raffinamento del design operativo del Segretario
> rispetto al PDF `zarsuit_segretario_design.pdf`, con focus su:
> output guard sul ritorno da Zarsuit, retry loop, budget di contesto,
> sessioni, modelli locali e detection.
>
> Questo documento **non sostituisce** il PDF di design e i contratti formali
> (`SecretaryContextRequest`, `SecretaryTaskRequest`, Risk Attestation).
> Li **applica** e ne fissa punti operativi rimasti aperti.

---

## 1. Stato dei modelli locali

**Decisione confermata.** Configurazione dual-model come da PDF sezione 3:

- **Sincrono (sempre caldo)**: Gemma 4 9B, quantizzazione Q6_K consigliata.
  Tool calling nativo, vision integrata, structured output affidabile.
- **Asincrono (caricato on-demand)**: Qwen3.5 9B di default, oppure
  Qwen3.6 27B per qualità superiore. Quantizzazione Q6_K (9B) o Q4_K_M (27B).

**Stato implementativo attuale (importante):**

- Tutti i modelli sopra sono **scaricati e testati** in locale su Ollama.
- Al momento è **implementato e attivo solo Gemma 4 9B** (variante 4B menzionata
  dall'utente come "gemma4B" attualmente in funzione).
- L'integrazione del consolidamento asincrono con Qwen3.5/3.6 e il pattern di
  swap di modelli via Ollama **non è ancora implementata**.

Il target operativo della latenza sincrona resta **1-3 secondi per turno**,
con timeout UX a 3 secondi (vedi sezione 6).

---

## 2. Budget di contesto a 3 livelli — regola del tetto adattivo

Confermata la struttura a 3 livelli definita nel PDF sezione 4 (identità
statica, working memory sanificata, recall on-demand).

**Raffinamento operativo:** il budget di token del livello 2 non è un valore
fisso, ma un **tetto adattivo per categoria di richiesta**. Il Segretario
riempie solo quello che effettivamente serve, non padda fino al tetto.

Matrice operativa:

| Categoria di richiesta | Tetto livello 2 | Note |
|---|---|---|
| Richiesta conversazionale normale | 4K token | Default |
| Richiesta che richiede recall storico esplicito | 4K working + 4K recall (livello 3) | Totale ~8K |
| Rifinitura Flow 02 con contesto raw post-Zarsuit | 2-3K token | Working ridotta perché si aggiungono dati raw del Vault |
| **Retry (seconda andata verso Zarsuit)** | **Tetto del default raddoppiato** | Hai già pagato la latenza percepita con il messaggio "ora si riprende", quindi vale la pena massimizzare la probabilità che il secondo tentativo vada |

**Sliding window**: la compaction droppa turni vecchi **solo se vicini al
tetto**. Sotto il tetto non si tocca nulla. Più semplice, più veloce, meno
sanitizzazioni inutili, meno invalidazione KV cache.

**Razionale della decisione**: scelta di compromesso tra performance e
design, presa dall'utente prima della chat. Il limite **non è di privacy**
(perché i dati che escono dal Segretario sono già tokenizzati e
generalizzati, vedi sezione 5), ma di latenza e qualità del ragionamento di
Zarsuit.

---

## 3. Retry loop — definizione completa

### 3.1 Quando il Segretario considera l'output di Zarsuit "non soddisfacente"

Il Segretario verifica **forma e rispetto del contratto**, non correttezza
fattuale. Triggera retry quando rileva una di queste condizioni:

1. **Zarsuit esce fuori dalla domanda / cambia contesto** rispetto al
   `user_visible_goal` definito nell'attestato di rischio.
2. **Output incompleto** o copre solo parzialmente quanto richiesto.
3. **Prompt injection rilevato** nell'output (pattern noti, schema rotto).
4. **Output strutturalmente malformato**: schema non conforme, JSON non
   parsabile, campi obbligatori mancanti.

**Cosa il Segretario NON verifica** (esplicitamente fuori scope, perché
rallenterebbe e non è il suo ruolo):

- Correttezza fattuale di quello che dice Zarsuit.
- Consistenza interna del ragionamento.
- Qualità semantica della risposta.

Se Zarsuit dice fesserie ben formate e conformi al contratto, **passa**. Sarà
l'utente a notarlo nei turni successivi della conversazione.

### 3.2 Detection via Attestato di Rischio

**Principio operativo (essenza del meccanismo):**

> *Il Segretario verifica che Zarsuit abbia rispettato il contratto che lui
> stesso ha firmato.*

L'attestato di rischio (Risk Attestation Exchange, PDF sezione 5.3) è un
**contratto a priori** tra Zarsuit e il Segretario. Quando l'output torna, il
Segretario non interpreta "ha risposto bene?", ma verifica meccanicamente
"ha rispettato il contratto?".

Checklist pass (deterministica, veloce):

- L'output cita campi solo dal `approved_context_projection`? ✓/✗
- L'output rispetta il `output_policy`
  (es. `boolean_only`, `summarized`, `privacy_projection`)? ✓/✗
- L'output suggerisce azioni solo dentro `allowed_next_steps`? ✓/✗
- L'output rispetta il `max_detail_level`
  (`minimum_necessary | summary | technical | operational`)? ✓/✗
- L'output risponde al `user_visible_goal` o sta parlando d'altro? ✓/✗

L'ultimo check è l'unico minimamente semantico, e può essere fatto come
**confronto di entità chiave**: si prendono le entità nominate nel
`user_visible_goal` e si verifica che appaiano nell'output. Se mancano del
tutto → retry. Se ci sono → fidati.

L'attestato di rischio fa il 90% del lavoro a monte; il guard a valle è
leggero.

### 3.3 Numero massimo di retry

**Max 2 retry.** Oltre, l'utente sta aspettando troppo.

- Primo retry: messaggio utente "Zarsuit è tutto fatto, ora si riprende..."
  (registro che rispecchia la personalità di zarsOS e dell'utente).
- Secondo retry (se necessario): "ci sto ancora lavorando, un attimo".
- Dopo il secondo retry fallito → failure: "non sono riuscito a completare
  la richiesta", audit registrato per review successiva.

### 3.4 Come viene riformulata la richiesta nel retry

- Il retry **non è una correzione esplicita** verso Zarsuit. Per Zarsuit
  deve sembrare una **nuova richiesta**.
- Il Segretario riformula la `SecretaryContextRequest` con projection
  eventualmente più mirata, più allargata, o con working memory più ampia
  (vedi sezione 2).
- Non si dice mai a Zarsuit "hai sbagliato perché X". Il guard resta una
  scatola nera dal lato Zarsuit.

### 3.5 Identificatori

- Il `request_id` originale dell'utente resta uno.
- Ogni andata Segretario↔Zarsuit ha un proprio `internal_request_id`
  distinto.
- L'audit ricostruisce la catena completa a posteriori, ma l'utente vede
  un solo task.

### 3.6 Projection allargabile autonomamente

Il Segretario **può allargare la projection autonomamente** nel retry, fino
al limite di dare anche grandi porzioni del Vault a Zarsuit, perché:

- I dati che escono dal Segretario sono **già tokenizzati e generalizzati**
  secondo le regole di privacy projection del Vault.
- La privacy non sta nel *quanto* il Segretario manda, ma nel *come* è
  proiettato.
- L'unico vero limite resta la **performance** (latenza, qualità del
  ragionamento di Zarsuit su contesto troppo ampio).

**Side-channel sul volume**: nominato e accettato nel threat model. Anthropic
non è nel set di attaccanti rilevanti; se Anthropic volesse sapere informazioni
generali dell'utente, le troverebbe più facilmente per altre vie. Decisione
chiusa.

### 3.7 Flow operativo riassuntivo

```text
Segretario valuta output di Zarsuit
├── accepted → rifinisce con raw → final_response all'utente
├── needs_refinement (retry 1 o 2)
│   → costruisce nuova SecretaryContextRequest (nuovo internal_request_id,
│     projection eventualmente allargata, budget livello 2 raddoppiato)
│   → rimanda a Zarsuit
│   → torna in valuta
└── rejected (max retry raggiunti o injection detected)
    → messaggio utente "non sono riuscito a completare la richiesta"
    → audit con reason strutturato
```

### 3.8 Audit del retry loop

Ogni retry è un evento separato nell'audit chain, con `reason` strutturato.
Valori previsti per `reason`:

- `goal_mismatch` (Zarsuit fuori contesto)
- `incomplete_output` (output parziale)
- `output_malformed` (schema rotto)
- `prompt_injection_detected`
- `contract_violation` (cita campi non approvati, viola `output_policy`,
  ecc.)

Questo permette di **misurare a posteriori** quanto spesso Zarsuit fallisce
e su che tipo di richieste, utile per capire se la projection di default è
troppo stretta o se serve riformulare gli intent.

---

## 4. Sessioni — non si chiudono durante una richiesta attiva

La doppia condizione di chiusura sessione definita nel PDF sezione 6.3
(`>24h dall'apertura E >1h inattività`) garantisce intrinsecamente che la
sessione **non possa chiudersi mentre c'è una richiesta attiva in corso**.

Motivo: se è in corso un retry, l'utente ha appena interagito, quindi i
60 minuti di inattività non possono essere maturati. La chiusura sessione
parte solo quando l'utente è effettivamente lontano o non sta usando
zarsOS in modo attivo.

Conseguenza pratica importante: questo è anche il **motivo per cui il
consolidamento asincrono può permettersi modelli pesanti** (Qwen3.5/3.6 27B
in Q4_K_M). Se il consolidamento si avvia, vuol dire che l'utente non sta
interagendo, quindi non c'è contesa per la VRAM con il modello sincrono.

---

## 5. Messaggio utente su latenza — timeout 3s

**Confermato timeout generale a 3 secondi.**

Quando un turno supera i 3 secondi (per retry o per qualsiasi altro motivo:
Ollama scaldato male, prima query post-consolidamento con Gemma appena
ricaricato, rete mobile scarsa), il client mostra il messaggio:

> Zarsuit è tutto fatto, ora si riprende...

Il messaggio rispecchia la personalità di zarsOS e dell'utente (registro
"persona dietro che si è momentaneamente staccata"). Funziona come
**loading indicator universale**, non legato specificamente al retry.

**Razionale del valore 3s:**

- Sotto 3s l'utente percepisce "fluido".
- Sopra 3s percepisce "sta pensando".
- Se il target operativo è 1-3s, 3s come soglia significa che il messaggio
  appare **solo quando si sta effettivamente sforando il target**.
- Più basso (1.5-2s) lo farebbe apparire troppo spesso (rumore).
- Più alto (5s) lo farebbe apparire troppo tardi (utente intanto si chiede
  se il sistema è morto).

---

## 6. Threat model — chiarimenti chiusi

- **Anthropic non è nel set di attaccanti rilevanti.** Eventuali side-channel
  di volume verso il provider cloud sono accettati. In futuro: LLM potente in
  locale per rimuovere anche questo livello.
- **Modelli locali**: confermato che girano in locale e nessun dato del Vault
  esce dall'hub se non come projection sanificata.
- Tutti gli invarianti di privacy del progetto principale (`AGENTS.md`,
  `il_segretario-threat-model.md`, sezione 9 del PDF di design) restano
  validi.

---

## 7. Riepilogo decisioni chiuse

- Separazione di ruoli Zarsuit/Segretario come da PDF.
- 3 livelli di carattere con **tetto adattivo per intent** (sezione 2).
- Retry loop **max 2 tentativi**, nuovo `internal_request_id` per andata,
  presentato a Zarsuit come nuova richiesta.
- **Projection allargabile autonomamente** dal Segretario nel retry,
  perché i dati sono tokenizzati.
- **Detection forma e contratto via attestato di rischio**, deterministica.
- **Detection contenuto fattuale NON fatta** (rallenta, non è ruolo del
  Segretario).
- Messaggio utente "Zarsuit è tutto fatto, ora si riprende..." su **timeout
  3s**.
- Sessione **non si chiude** durante richiesta attiva (garantito dalla
  doppia condizione).
- **Side-channel volume verso Anthropic = accettato** nel threat model.
- **Modelli sincrono (Gemma 4 9B) e asincrono (Qwen3.5/3.6 9B-27B)** scaricati
  e testati. **Implementato e attivo al momento solo Gemma 4 9B** (variante
  4B come stato corrente). Integrazione swap di modelli e consolidamento
  asincrono **non ancora implementati**.

---

## 8. Postilla — argomenti rimandati a chat dedicate

I seguenti punti sono stati **esplicitamente parcheggiati** in questa chat
per essere ripresi in sessioni dedicate, perché richiedono approfondimento
prima di decidere e l'utente vuole avere base prima di "dare sentenze".

### 8.1 Prompt injection detection

**Stato**: aperto.

Da decidere il meccanismo concreto. Le opzioni elencate nella chat erano:

1. **Regex/keyword list** su pattern noti
   (`"ignore previous"`, `"system:"`, `"you are now"`, `"</system>"`, ecc).
   Veloce, copre ~70% dei casi, bypassabile con creatività.
2. **Detection strutturale**: l'output di Zarsuit deve essere JSON
   schema-conforme con campi specifici; tutto ciò che è fuori dallo schema
   viene scartato. Più robusto perché non lascia spazio a "testo libero".
3. **LLM classifier dedicato**: Gemma classifica
   "questo output contiene tentativi di scavalcare le policy?".
   Costoso, accurato.

Combo proposta da valutare: **strutturale + regex come safety net + LLM
classifier solo per casi edge** se si vedono cose passare.

L'utente vuole approfondire prima di decidere.

### 8.2 Recall on-demand — livello 3

**Stato**: aperto.

Da decidere il meccanismo di retrieval per le richieste con
`intent_type: MEMORY_LOOKUP`. Le opzioni elencate erano:

1. **FTS5 su SQLite**: keyword-based, deterministico, zero dipendenze nuove.
   Limite: manca recall semantico.
2. **Embeddings via Ollama** (es. `nomic-embed-text` 768 dim, 274MB, oppure
   `mxbai-embed-large` 1024 dim, 670MB). Recall semantico vero, gestisce
   parafrasi. Storage proposto: `sqlite-vec`. Re-indexing su filesystem
   watcher in batch.
3. **Ibrido**: FTS5 per recall preciso + embeddings per recall semantico,
   merge con reciprocal rank fusion.

Parametri operativi rimasti da decidere se si va su embeddings:

- Modello embedding (nomic vs mxbai).
- Chunking (nota intera vs split per sezioni H2).
- Storage (sqlite-vec vs file pickle/numpy).
- Frequenza re-indexing.
- Pre-filtering privacy (escludere sempre `self/profile/`,
  `meta/privacy_map.local.json`, `raw/elaborati/` prima della query).

L'utente vuole approfondire prima di decidere.

### 8.3 Promemoria

Quando si riapre la chat dedicata su prompt injection o recall livello 3,
ricordare di **ripartire da questo documento** per non perdere il contesto
delle decisioni già prese, e in particolare:

- l'attestato di rischio come meccanismo di detection principale (sezione 3.2);
- il principio "tutto è tokenizzato quindi la privacy non limita il volume"
  (sezione 3.6) che cambia i requisiti del retrieval livello 3;
- il fatto che al momento solo Gemma 4 9B è implementato (sezione 1).
