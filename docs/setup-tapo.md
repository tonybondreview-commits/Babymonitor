# 🐣 Camere TP-Link Tapo (C100 / C110 / C200 / C210 / C310...)

Le Tapo funzionano benissimo come baby monitor, ma hanno **una regola che
blocca quasi tutti**: il video RTSP **non** usa l'account TP-Link con cui entri
nell'app. Serve un **Account telecamera** creato apposta.

Se il wizard dice **"utente/password rifiutati dalla camera"** ed è una Tapo,
è al 99% questo il motivo: la camera risponde (l'IP è giusto), ma rifiuta le
credenziali.

---

## 1. Crea l'Account telecamera

Nell'app **Tapo**, sul telefono:

1. Apri la tua camera.
2. Tocca l'**ingranaggio ⚙** in alto a destra (Impostazioni dispositivo).
3. **Avanzate** → **Account telecamera**
   (in alcune versioni: *Impostazioni avanzate → Account telecamera/RTSP*).
4. Inserisci un **nome utente** e una **password** nuovi — li scegli tu, non
   c'entrano nulla con l'account TP-Link — e **salva**.

> Suggerimento: usa una password **senza caratteri strani** (solo lettere e
> numeri). Alcune camere gestiscono male `@`, `:` e `/` dentro l'URL RTSP.

## 2. Trova (e fissa) l'indirizzo IP

- App Tapo → ⚙ → **Avanzate** → *Informazioni dispositivo* → indirizzo IP,
  oppure dalla pagina del router fra i dispositivi collegati.
- Nel router assegna alla camera un **IP fisso** (DHCP reservation): così non
  cambia e il baby monitor non la "perde" dopo un riavvio.

Il wizard sa anche cercarla da solo: **🔍 Cerca camera in rete**.

## 3. Configura il Baby Monitor

Nel wizard inserisci:

| Campo | Valore |
|---|---|
| Indirizzo IP | quello della camera, es. `192.168.1.64` |
| Utente | **quello dell'Account telecamera** |
| Password | **quella dell'Account telecamera** |

Il resto lo trova da solo: prova i percorsi RTSP e sceglie il primo che
risponde. Sulle Tapo sono:

- `rtsp://utente:password@IP:554/stream1` → **alta qualità** (1080p)
- `rtsp://utente:password@IP:554/stream2` → **leggero** (360p, consigliato per
  il rilevamento del movimento)

## 4. Movimento della camera (solo modelli motorizzati, es. C210)

Le Tapo espongono ONVIF sulla porta **2020** (le Fredi/Yoosee usano la 5000).
Il baby monitor la prova da solo; nell'app Flutter puoi impostarla a mano da
**Impostazioni → Avanzate → Porta ONVIF**. Le credenziali sono le stesse
dell'Account telecamera.

---

## Se ancora non va

| Sintomo | Causa probabile |
|---|---|
| `utente/password rifiutati dalla camera` | Account telecamera non creato, oppure stai usando l'account TP-Link. Ricrealo e riprova. |
| `timeout` / `no route to host` | IP sbagliato o camera su un'altra rete WiFi (attenzione alle reti "ospiti" e alle bande 2.4/5 GHz separate). |
| `nessun percorso video valido trovato` | Firmware che espone percorsi diversi: prova a mano `stream1` / `stream2` nelle impostazioni avanzate. |
| Video a scatti | Usa lo stream **leggero** (`stream2`) o abbassa la qualità nel menu dell'app. |
| Funziona e poi si blocca | Le Tapo accettano poche sessioni RTSP insieme: chiudi l'app Tapo e altri visualizzatori mentre usi il baby monitor. |

## Verifica veloce da riga di comando

Sul "cervello" (Raspberry Pi, mini-PC, Termux):

```bash
ffplay -rtsp_transport tcp "rtsp://UTENTE:PASSWORD@IP:554/stream2"
```

Se questo comando mostra il video, il baby monitor funzionerà; se dà
`401 Unauthorized`, il problema sono le credenziali (torna al punto 1).
