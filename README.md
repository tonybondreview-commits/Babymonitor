# 👶 Baby Monitor per camere Fredi / Yoosee

Trasforma una comune camera da interno **Fredi** (app **Yoosee**) in un baby
monitor con due funzioni:

1. **Rilevamento del movimento** → quando il bimbo si muove, appare un
   **popup** (con suono e vibrazione) sullo schermo dell'app.
2. **Ninna nanne** → 4-5 brani che fai partire con un tap e suonano dal
   dispositivo vicino al bimbo.

Il tutto **100% offline**, sulla rete di casa: nessun cloud, nessun
abbonamento, nessun dato che esce da casa.

---

## ⚠️ Come funziona davvero (leggi prima)

L'app **Yoosee è un sistema chiuso e non modificabile**: non si possono
aggiungere popup o pulsanti *dentro* Yoosee. Questo progetto è
un'**app companion** separata che sfrutta lo stream video della camera
(protocollo **RTSP/ONVIF**) sulla rete locale.

```
[Camera Fredi] --WiFi/RTSP--> [CERVELLO: sempre acceso]
                                 · legge il video
                                 · rileva il movimento
                                 · serve la webapp sulla rete di casa
                                        │
                                        ▼
                              [iPad / telefono: apre un link]
                               video live + popup + ninna nanne
```

- **Cervello** = un dispositivo **sempre acceso** che fa l'elaborazione:
  Raspberry Pi, mini-PC, o un **vecchio telefono Android** (via Termux).
  ⚠️ **Non può essere un iPhone/iPad**: iOS chiude le app in background e non
  può analizzare il video 24/7.
- **Schermo** = iPad o telefono (iOS **o** Android) su cui apri la webapp.
  L'**iPad vicino alla culla è perfetto** come schermo sempre acceso: mostra
  il video, riceve i popup e suona le ninna nanne dal suo altoparlante.

### Cosa aspettarsi
| Funzione | Affidabilità | Note |
|---|---|---|
| Popup movimento (app **aperta**) | ✅ Alta | Funziona offline su iOS e Android |
| Popup con app **chiusa/telefono bloccato** | ❌ Non incluso | Bloccato da iOS; su Android si può aggiungere in futuro |
| Ninna nanne dal dispositivo (browser) | ✅ Alta | Il modo consigliato |
| Ninna nanne dall'altoparlante *della camera* | ⚠️ Dipende dal modello | Le Yoosee usano audio proprietario; non garantito |

---

## 🔧 1. Prepara la camera

1. Apri l'app **Yoosee** → impostazioni della camera → attiva **ONVIF**
   (a volte chiamato "protocollo terze parti" / "RTSP"). Imposta o annota
   **utente e password ONVIF**.
2. Trova l'**indirizzo IP** della camera (nella pagina del router, tra i
   dispositivi connessi, oppure nell'app Yoosee → info dispositivo).
   Conviene assegnarle un **IP fisso** dal router, così non cambia.

Gli URL RTSP tipici delle Fredi/Yoosee sono:
- Alta qualità: `rtsp://utente:password@IP:554/onvif1`
- Leggero (consigliato per il rilevamento): `rtsp://utente:password@IP:554/onvif2`

---

## 💻 2. Installa sul "cervello"

Serve **Python 3.9+**. Sul dispositivo sempre acceso:

```bash
git clone <questo-repo> Babymonitor
cd Babymonitor
pip install -r requirements.txt
```

> Su Raspberry Pi / Debian, se `opencv-python-headless` desse problemi:
> `sudo apt install python3-opencv` e poi installa il resto.

---

## ⚙️ 3. Configura

```bash
cp config.example.yaml config.yaml
```

Apri `config.yaml` e imposta **IP**, **utente** e **stream** della camera.
Per la password, il modo più sicuro è **non scriverla nel file** ma passarla
come variabile d'ambiente:

```bash
export CAMERA_PASSWORD="la-tua-password"
```

(`config.yaml` e i file audio **non** vengono caricati su git.)

---

## 🎵 4. Aggiungi le ninna nanne

Metti 4-5 file audio (`.mp3`, `.wav`, `.ogg`, `.m4a`…) nella cartella
`lullabies/`. Il nome del file diventa il titolo nell'app. Vedi
`lullabies/README.md`.

---

## ▶️ 5. Avvia

```bash
python run.py
```

Vedrai qualcosa come:
```
[baby-monitor] Apri dal telefono/iPad:  http://<ip-di-questo-dispositivo>:8080
```

Sul telefono/iPad (**stessa rete WiFi**) apri il browser e vai a:
```
http://IP-DEL-CERVELLO:8080
```
(esempio: `http://192.168.1.50:8080`)

### "Installa" come app (consigliato)
- **iPhone/iPad (Safari):** tocca *Condividi* → **Aggiungi a Home**.
- **Android (Chrome):** menu ⋮ → **Installa app / Aggiungi a Home**.

Così avrai un'icona come un'app vera, a schermo intero.

---

## 📱 Come si usa

- **Video live** in alto (aggiornato in tempo reale).
- **Interruttore "Rilevamento movimento"**: on/off.
- **Sensibilità** (1–100): più alta = nota anche piccoli movimenti; più bassa
  = meno falsi allarmi. Parti da ~55 e regola.
- Quando il bimbo si muove → **popup "Il bimbo si è mosso!"** + beep +
  vibrazione. Tieni lo schermo aperto vicino a te (come un baby monitor).
- **Ninna nanne**: tocca un brano per farlo partire; attiva **ripeti** per il
  loop. Suonano dall'altoparlante del dispositivo → tieni quel dispositivo
  vicino alla culla.

---

## 🔁 Avvio automatico (opzionale)

**Raspberry Pi / Linux (systemd):** crea `/etc/systemd/system/babymonitor.service`:
```ini
[Unit]
Description=Baby Monitor
After=network-online.target

[Service]
WorkingDirectory=/home/pi/Babymonitor
Environment=CAMERA_PASSWORD=la-tua-password
ExecStart=/usr/bin/python3 run.py
Restart=always

[Install]
WantedBy=multi-user.target
```
Poi: `sudo systemctl enable --now babymonitor`.

**Vecchio Android (Termux):** installa Termux, `pkg install python`, poi
installa i requisiti e lancia `python run.py`. Tieni lo schermo del telefono
acceso / disattiva l'ottimizzazione batteria per Termux.

---

## 🩺 Problemi comuni

| Sintomo | Soluzione |
|---|---|
| "Camera offline" | Verifica IP, utente/password, e che **ONVIF** sia attivo in Yoosee. Prova `stream: "main"`. |
| Non apre la pagina dal telefono | Devono essere sulla **stessa rete WiFi**. Controlla il firewall sul cervello (porta 8080). |
| Troppi falsi allarmi | Abbassa la **sensibilità**, aumenta `consecutive_frames` o `cooldown_seconds`. |
| Non rileva movimenti piccoli | Alza la **sensibilità**; usa lo stream `main`. |
| Ninna nanne non partono su iPhone | Tocca prima lo schermo una volta (iOS richiede un'interazione per l'audio). |

---

## 🧪 Test

```bash
pip install pytest
python -m pytest tests/ -q
```

## 🗺️ Struttura del progetto
```
babymonitor/      cuore dell'app (config, camera, movimento, server, ninna nanne)
web/              webapp (PWA): interfaccia, popup, video, service worker
lullabies/        i tuoi file audio (non versionati)
tests/            test del rilevamento movimento
run.py            avvio
config.example.yaml   modello di configurazione
```

## 🔒 Privacy
Video, movimento e audio restano **sulla rete di casa**. Nessun dato viene
inviato a server esterni. La password della camera resta solo in locale.
