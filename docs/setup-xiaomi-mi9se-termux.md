# 🧠 Usare uno Xiaomi Mi 9 SE (o altro Android) come "cervello"

Il Mi 9 SE è perfetto come dispositivo sempre acceso che legge il video della
camera, rileva il movimento e serve la webapp. Gira dentro **Termux** (un
terminale Linux per Android). Tutto resta offline, sulla rete di casa.

> ⚠️ Due punti delicati, spiegati sotto: **OpenCV su Termux** (si installa con
> `pkg`, non con `pip`) e le **impostazioni MIUI** per non farlo chiudere.

---

## 1. Installa Termux (dalla fonte giusta)

Installa Termux da **F-Droid**, NON dal Play Store (quella del Play Store è
vecchia e non aggiornabile):

- App F-Droid: https://f-droid.org → cerca **Termux**
- (oppure scarica l'APK di F-Droid da https://f-droid.org e poi Termux da lì)

Consigliato anche **Termux:Boot** (stesso F-Droid) per l'avvio automatico al
riavvio del telefono.

---

## 2. Prepara Termux

Apri Termux e digita (una riga alla volta):

```bash
pkg update && pkg upgrade -y
pkg install -y python opencv-python git
pip install flask pyyaml
termux-setup-storage   # dà a Termux accesso alla memoria (per le ninna nanne)
```

> **Perché `pkg install opencv-python` e non `pip`?** Su Android `pip install
> opencv-python` prova a compilare da zero e fallisce. Il pacchetto nativo di
> Termux (`opencv-python`) è già pronto e include `cv2` e `numpy`.
> Per questo, sul telefono **NON** usare `pip install -r requirements.txt`
> (installeresti opencv sbagliato): installa Flask e PyYAML a mano come sopra.

---

## 3. Scarica il progetto e configura

```bash
git clone <URL-DEL-REPO> Babymonitor
cd Babymonitor
cp config.example.yaml config.yaml
nano config.yaml       # metti IP, utente e stream della camera; salva con CTRL+O, esci con CTRL+X
```

Password della camera senza scriverla nel file:
```bash
export CAMERA_PASSWORD="la-tua-password"
```

Metti le ninna nanne in `~/Babymonitor/lullabies/` (puoi copiarle con un file
manager nella cartella di Termux, o scaricarle).

---

## 4. Evita che Android/MIUI lo chiuda (IMPORTANTE)

MIUI chiude le app in background in modo aggressivo. Fai **tutto** questo:

1. **Wake-lock di Termux** — impedisce alla CPU di addormentarsi.
   In Termux digita:
   ```bash
   termux-wake-lock
   ```
   (oppure tira giù la notifica di Termux e tocca "Acquire wakelock").

2. **Autostart**: Impostazioni → App → Gestisci app → **Termux** →
   attiva **Autostart**.

3. **Batteria senza restrizioni**: stessa schermata di Termux →
   **Risparmio energetico** → **Nessuna restrizione**.

4. **Blocca Termux nei recenti**: apri le app recenti, tieni premuto su
   Termux → **icona lucchetto** (bloccato = non viene chiuso).

5. (Facoltativo) Impostazioni → **Batteria** → disattiva ottimizzazioni per
   Termux.

---

## 5. Avvia

```bash
cd ~/Babymonitor
python run.py
```

Vedrai l'indirizzo, tipo `http://192.168.1.50:8080`. Dall'**iPad/telefono**
(stessa rete WiFi) apri quell'indirizzo nel browser e "Aggiungi a Home".

> Trova l'IP del Mi 9 SE: in Termux `ip addr | grep 'inet '` oppure
> Impostazioni → WiFi → tocca la rete. Meglio ancora: dal **router** assegna
> un **IP fisso** al Mi 9 SE, così non cambia mai.

---

## 6. Avvio automatico al riavvio (facoltativo, con Termux:Boot)

Crea lo script di avvio:
```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/babymonitor.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd ~/Babymonitor
export CAMERA_PASSWORD="la-tua-password"
python run.py
EOF
chmod +x ~/.termux/boot/babymonitor.sh
```
Apri **Termux:Boot** una volta (per abilitarlo). Al riavvio partirà da solo.

---

## Uso "tutto in uno" (un solo dispositivo)

Se vuoi usare **solo il Mi 9 SE** vicino alla culla (cervello + schermo +
altoparlante): lascia `python run.py` attivo in Termux, poi apri **Chrome**
sullo stesso telefono su `http://localhost:8080`. Vedrai video e popup e
potrai far partire le ninna nanne dall'altoparlante del telefono. In questo
caso, per ricevere i popup anche in un'altra stanza, apri la stessa pagina
anche sul tuo telefono personale.

---

## Problemi tipici su Android/MIUI

| Sintomo | Soluzione |
|---|---|
| Dopo un po' smette di funzionare | Non hai fatto il wake-lock o il blocco nei recenti (vedi §4). |
| `cv2` non trovato | Hai usato `pip` per opencv: usa `pkg install opencv-python`. |
| "Camera offline" | Controlla IP/credenziali e che ONVIF sia attivo in Yoosee. |
| Non raggiungo la pagina dall'iPad | Stessa rete WiFi? IP del Mi 9 SE giusto? Riavvia `run.py`. |
| Consuma troppa batteria | Tienilo in carica: da "cervello" 24/7 conviene sempre collegato. |
