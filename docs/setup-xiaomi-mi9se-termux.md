# 🧠 Usare un telefono Android come "cervello" (Xiaomi, Pixel, ecc.)

Un telefono Android sempre acceso (es. **Xiaomi Mi 9 SE** o **Google Pixel**)
è perfetto per leggere il video della camera, rilevare il movimento e servire
la webapp. Gira dentro **Termux** (un terminale Linux per Android). Tutto
resta offline, sulla rete di casa.

> ⚠️ Due punti delicati, spiegati sotto: **OpenCV su Termux** (si installa con
> `pkg`, non con `pip`) e le **impostazioni anti-chiusura** (poche su Pixel,
> più numerose su Xiaomi/MIUI).

---

## 1. Installa Termux (dalla fonte giusta)

Installa Termux da **F-Droid**, NON dal Play Store (quella del Play Store è
vecchia e non aggiornabile):

- App F-Droid: https://f-droid.org → cerca **Termux**
- (oppure scarica l'APK di F-Droid da https://f-droid.org e poi Termux da lì)

Consigliato anche **Termux:Boot** (stesso F-Droid) per l'avvio automatico al
riavvio del telefono.

---

## 2. Scarica il progetto e installa (un comando)

Apri Termux:

```bash
pkg install -y git
git clone <URL-DEL-REPO> Babymonitor
cd Babymonitor
bash scripts/install-termux.sh
```

L'installer fa **tutto** da solo: installa Python + OpenCV (col pacchetto
Termux, non con pip), Flask e PyYAML, dà l'accesso alla memoria e prepara
l'avvio automatico. Non devi modificare nessun file: la **camera si configura
poi dal wizard** dentro l'app.

> **Perché non `pip install opencv-python`?** Su Android quella via prova a
> compilare da zero e fallisce. L'installer usa `pkg install opencv-python`
> (già pronto). Per lo stesso motivo sul telefono **non** usare
> `pip install -r requirements.txt`.

---

## 3. Evita che Android lo chiuda (IMPORTANTE)

> 📱 **Hai un Google Pixel (Android "stock", es. Pixel 9a/10a)?** È più facile:
> non c'è l'Autostart di MIUI. Ti basta: **Impostazioni → App → Termux →
> Batteria → "Senza restrizioni"** (o "Illimitato"), tenere Termux aperto in
> un riquadro dei recenti, e fare `termux-wake-lock`. Salta i passi specifici
> di Xiaomi qui sotto.

Su Xiaomi/MIUI, che chiude le app in background in modo aggressivo, fai
**tutto** questo:

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

## 4. Avvia

```bash
termux-wake-lock
cd ~/Babymonitor
python run.py
```

Vedrai l'indirizzo, tipo `http://192.168.1.50:8080`. Dall'**iPad/telefono**
(stessa rete WiFi) apri quell'indirizzo nel browser, segui il **wizard** per
configurare la camera, poi "Aggiungi a Home".

> Trova l'IP del Mi 9 SE: in Termux `ip addr | grep 'inet '` oppure
> Impostazioni → WiFi → tocca la rete. Meglio ancora: dal **router** assegna
> un **IP fisso** al Mi 9 SE, così non cambia mai.

---

## 5. Avvio automatico al riavvio (facoltativo, con Termux:Boot)

L'installer ha già creato lo script `~/.termux/boot/babymonitor.sh`. Basta
installare l'app **Termux:Boot** (da F-Droid) e aprirla una volta: al riavvio
del telefono il baby monitor partirà da solo.

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
