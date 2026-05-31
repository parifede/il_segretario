# zarsOS — Livello Multi-Device

> Documento di sintesi delle decisioni architetturali per il livello multi-device di zarsOS.
>
> Scope: definire come Zarsuit/Segretario gestiscono un singolo utente che accede da più dispositivi (PC, smartphone, eventuali altri client) mantenendo contesto e stato condiviso.
>
> Out of scope: hardware, modelli LLM specifici, implementazione interna del Segretario e del Vault.

---

## 1. Principio architetturale fondamentale

```text
Stato condiviso nell'hub.
Vista locale per device.
Client stupidi, intelligenza centralizzata.
```

L'hub centrale è l'unico depositario della "mente" di Zarsuit. I client sono pure interfacce di I/O: mandano richieste, ricevono risposte, mostrano localmente solo i propri turni. La working memory, la long-term memory, il carattere di Zarsuit e tutto lo stato vivono esclusivamente nell'hub.

Conseguenza pratica: aprendo l'app su un device "nuovo" si vede una schermata vuota (nessuna history sincronizzata), ma chiedendo "ricordati di quello di cui parlavamo prima" Zarsuit risponde correttamente perché il contesto vive nell'hub.

---

## 2. Topologia

### Hub centrale

- Macchina sempre accesa (desktop con GPU per LLM locale del Segretario).
- Ospita: Segretario, Vault, LLM locale, Gateway, Job Store, audit, bacheca.
- Punto unico di esecuzione delle policy e del Permission Kernel.

### Client

- Tipologie: app PC, app smartphone, eventuali altri canali futuri.
- Funzioni: input UI, rendering output, buffer offline.
- Nessuna logica di business, nessuno stato condiviso, nessuna cache della "mente".
- Auth via token per device (generato in pairing, salvato in keychain).

### Rete

- Tailscale o WireGuard come overlay privato.
- Solo i device autorizzati raggiungono l'hub.
- Niente esposizione pubblica dell'hub su Internet.

### Canale Telegram

- Status: temporaneo, destinato a essere rimosso.
- Sostituito da app dedicata con schermata Segretario vincolata.
- Bot token (se ancora attivo durante la transizione) vive solo sull'hub, mai sui client.

---

## 3. Conversazione: storage e proiezione

### Sorgente primaria

- Log conversazionale append-only nel Vault.
- Formato: JSONL strutturato, una entry per messaggio.
- Owned dal Segretario, mai accessibile direttamente da Zarsuit né dai client.

### Schema entry

```yaml
message_id: "uuid"
timestamp: "ISO-8601"
device_id: "string"
channel: "pc | mobile | other"
role: "user | zarsuit | segretario"
session_id: "string"
content_ref: "reference into vault"
```

`content_ref` perché il contenuto effettivo resta nel Vault, non nel log indicizzabile.

### Proiezione leggibile

- File `chat.md` rigenerato dal Segretario a partire dal JSONL.
- Stesso pattern di `bacheca.json` → `bacheca.md` già presente nell'architettura.
- La proiezione `.md` non è sorgente, è solo output umano-leggibile su richiesta.

---

## 4. Carattere di Zarsuit: 3 livelli ricomposti

Il Segretario, a ogni chiamata di Zarsuit, ricompone un pacchetto contesto a tre livelli:

### Livello 1 — Identità statica

- Personalità, tono, stile, "il fratello" come metafora.
- Cambia raramente, può essere cached.
- È il carattere fondamentale di Zarsuit, indipendente dalla conversazione.

### Livello 2 — Working memory sanificata

- Ultimi N turni della sessione attiva.
- Rigenerato a ogni turno.
- Sanificato dal Segretario: tokenizzato, censurato, generalizzato dove necessario.
- Cross-device per definizione: turni dal PC e dal telefono vivono nella stessa working memory.

### Livello 3 — Recall on-demand

- Conoscenza consolidata da sessioni passate.
- Richiamata solo se la richiesta corrente lo richiede esplicitamente.
- Zarsuit deve "pensarci": fa richiesta di contesto al Segretario, che cerca nel Vault e proietta.
- Funziona come la memoria a lungo termine umana: non sempre presente, ma recuperabile.

### Composizione

I tre livelli sono concettualmente separati ma il Segretario li fonde in un'unica risposta a Zarsuit. Separazione interna, output unificato.

---

## 5. Sessioni

### Apertura

- Una sola sessione attiva globale (single-user, una mente).
- `session_id` univoco per sessione.

### Chiusura

Una sessione viene chiusa se e solo se entrambe le condizioni sono vere:

```text
ore_da_apertura >= 24 AND minuti_inattivita >= 60
```

Questa logica permette conversazioni lunghe senza interruzioni mentre sei attivo, ma chiude la sessione quando ti fermi davvero.

### Cosa succede alla chiusura

1. Log corrente (`session_NNNN.jsonl`) viene chiuso e sigillato.
2. Job asincrono di consolidamento: il Segretario estrae fatti rilevanti, decisioni, preferenze nuove emerse, aggiorna la knowledge nel Vault.
3. Log archiviato resta accessibile per recall futuri.
4. Nuova `session_NNNN+1.jsonl` parte vuota.

### Consolidamento asincrono

- Non blocca l'apertura della nuova sessione.
- Pattern write-then-rename per atomicità (resiste a riavvii dell'hub).
- Se l'hub si riavvia durante consolidamento, il job riprende o ricomincia da zero senza corrompere il Vault.

---

## 6. Ordering cross-device

### Strategia

- Ordering server-side con timestamp client validato.

### Regola di validazione

Al ricevere ogni messaggio, l'hub esegue:

```python
delta = abs(hub_now - client_sent_at)
if delta > 5 * 60:  # 5 minuti
    log_anomaly(device_id, delta)
    timestamp_usato = hub_now
else:
    timestamp_usato = client_sent_at
```

### Razionale

- Il client manda il proprio `client_sent_at`, fedele al momento reale dell'azione utente.
- L'hub valida contro il proprio orologio (riferimento autoritativo).
- Tolleranza 5 minuti: assorbe latenza di rete e drift normale.
- Anomalie: timestamp client scartato, sostituito con `hub_now`, anomalia loggata in audit.

---

## 7. Idempotenza

### Strategia

- `request_id` UUID generato client-side.
- Mantenuto invariato su retry.

### Comportamento hub

- Se l'hub vede lo stesso `request_id` due volte:
  - Non riesegue la richiesta.
  - Restituisce la risposta già calcolata.
- Garantisce safety per buffer offline e retry di rete.

---

## 8. Coda FIFO

### Strategia

- Coda globale single-user all'ingresso del Gateway.
- FIFO semplice, niente partizionamento per device.

### Razionale

- Single-user: massimo realistico due richieste in coda (sto scrivendo da PC, tiro fuori il telefono).
- La seconda aspetta che la prima completi il giro Zarsuit → Segretario → risposta.
- Evita race condition senza overhead di concorrenza.

---

## 9. Buffer offline lato client

### Comportamento

- Se l'hub è irraggiungibile, il client bufferizza localmente la richiesta.
- Retry automatico a backoff esponenziale al ritorno della connessione.
- `request_id` mantenuto invariato per garantire idempotenza.

### Pattern di riferimento

- Simile al comportamento di Claude quando si raggiunge il limite di utilizzo: bufferizza e ritenta.
- Simile a Slack/WhatsApp per messaggi inviati offline.

---

## 10. Vista locale per device

### Cosa vede il client

- Solo i propri turni: messaggi inviati da quel device e relative risposte di Zarsuit.
- History locale persistita come cache UI, non come sorgente di verità.
- La history locale può essere persa senza danni: la mente vera è nell'hub.

### Cosa NON fa il client

- Non sincronizza history con altri device.
- Non riceve push real-time di turni generati da altri device.
- Non ha un endpoint "give me history" verso l'hub.

### Esempio concreto

```text
PC, ore 14:00: chatti per un'ora, parli del progetto X.
Telefono, ore 15:30: apri l'app, schermata vuota.
Telefono, ore 15:31: scrivi "ricordati di X?"
Risposta: Zarsuit risponde correttamente, il contesto vive nell'hub.
```

---

## 11. Auth client → hub

### Pairing iniziale

- Token per device generato una volta sola in fase di setup.
- Salvato nel keychain del device (iOS Keychain, Android Keystore, Windows Credential Manager, ecc.).

### Trasporto

- Token nell'header di ogni richiesta verso l'hub.
- TLS via Tailscale/WireGuard (overlay di rete privato).

### Razionale single-user

- Niente OAuth, niente refresh token, niente flussi enterprise.
- Single-user: se un attaccante ha root sul device, ha già perso la partita comunque.
- Semplicità vince complessità in questo scenario.

---

## 12. Schema Gateway esteso

Estensione minima del Gateway esistente per supportare il multi-device:

```yaml
gateway_request:
  request_id: "uuid (client-generated)"
  client_sent_at: "ISO-8601 (client)"
  device_id: "string"
  channel: "pc | mobile | other"
  user_id: "local_user (sempre lo stesso)"
  session_id: "current session id"
  raw_user_text: "string"
```

### Cosa cambia

- Aggiunta di `device_id` e `client_sent_at`.
- Validazione timestamp con tolleranza 5 minuti.
- Idempotenza via `request_id`.
- Pre-step: ContextBroker chiede al Segretario carattere + contesto recente.
- Post-step: scrittura del turno nel log conversazionale del Vault via Segretario.

### Cosa NON cambia

- Permission Kernel, Output Guard, Flow 02, Job Store, audit, bacheca: invariati.
- Tutte le policy esistenti continuano ad applicarsi.

---

## 13. Fattibilità

### Componenti già esistenti nel codice

- Hub sempre acceso con servizi locali.
- Job Store con lock per concorrenza.
- Audit append-only.
- Log JSONL come sorgente con proiezione `.md`.
- Permission Kernel, Output Guard, Flow 02.
- Risk Attestation Exchange, SecretaryContextRequest, SecretaryTaskRequest.

### Componenti standard del settore

- Tailscale/WireGuard: setup di mezz'ora.
- Token per device in keychain: pattern di ogni app mobile.
- Buffer offline con retry e idempotenza UUID: pattern di Slack, WhatsApp, Claude.
- Coda FIFO single-user: lista in memoria con lock.
- Validazione timestamp: poche righe di codice.
- Sessione con doppia condizione: logica banale.

### Componenti specifici di zarsOS

- Carattere a 3 livelli: estensione del `SecretaryContextRequest` esistente.
- Consolidamento asincrono: nuovo tipo di job nel Job Store con write-then-rename.

### Unico vero collo di bottiglia

- Latenza del Segretario locale quando ricompone il carattere a 3 livelli.
- Va benchmarkato sul modello/hardware effettivo (Ministral 8B su 4080/5080).
- 1-3 secondi accettabili, oltre i 4-5 secondi diventa scomodo.

### Conclusione

Stai *componendo* primitivi conosciuti in un'architettura nuova. La novità sta nella composizione, non nei mattoni. Ogni componente è fattibile da solo, e messi insieme non si rompono a vicenda.

---

## 14. Riepilogo invarianti aggiunti

```text
1. La "mente" di Zarsuit è una sola e vive nell'hub.
2. Ogni client è stateless rispetto allo stato condiviso.
3. Il log conversazionale è append-only, JSONL, owned dal Segretario.
4. Zarsuit non legge mai il log conversazionale raw, solo proiezioni del Segretario.
5. Il carattere di Zarsuit è ricomposto a ogni chiamata dal Segretario.
6. Working memory cross-device, vista UI per device.
7. Timestamp client validati contro orologio hub (tolleranza 5 minuti).
8. Idempotenza via request_id UUID generato client-side.
9. Coda FIFO single-user al Gateway.
10. Sessione chiusa solo se >24h da apertura AND >1h inattiva.
11. Consolidamento di fine sessione è asincrono e atomico (write-then-rename).
12. Buffer offline lato client con retry preservando request_id.
13. Auth via token per device in keychain, niente OAuth.
14. Telegram canale temporaneo, in dismissione.
```

---

## 15. Done definition

Il livello multi-device è completo quando:

```text
1. Il Gateway accetta device_id e client_sent_at.
2. La validazione timestamp con tolleranza 5 minuti è attiva.
3. L'idempotenza via request_id funziona end-to-end.
4. La coda FIFO global single-user è in produzione.
5. Il log conversazionale JSONL è gestito dal Segretario nel Vault.
6. La proiezione chat.md viene rigenerata correttamente.
7. Il SecretaryContextRequest estensione "carattere a 3 livelli" è implementato.
8. La sessione si chiude solo con la doppia condizione.
9. Il consolidamento asincrono di fine sessione gira come job.
10. Il client ha buffer offline con retry e mantiene request_id.
11. Almeno 2 device (PC + smartphone) si connettono via Tailscale/WireGuard.
12. Auth per device con token in keychain è attiva.
13. Lo stato condiviso e la vista locale funzionano come da specifica.
```

---

## 16. Non-obiettivi

Esplicitamente fuori scope per questa fase:

- Sync UI cross-device in tempo reale (push websocket, history mirroring).
- Endpoint client "give me history" verso l'hub.
- CRDT o stato distribuito (sproporzionato per single-user).
- Multi-utente (single-user è un vincolo di design).
- Cloud relay come architettura primaria.
- Mantenimento di Telegram come canale di lungo periodo.
