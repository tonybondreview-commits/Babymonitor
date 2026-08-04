# Baby Monitor — app nativa Flutter

App **nativa** (Android/iOS) che trasforma una telecamera **ONVIF/RTSP**
(Fredi / Yoosee e simili) in un baby monitor, **senza nessun dispositivo
"cervello" di mezzo**.

A differenza della webapp (cartella `../babymonitor`, che resta come backup),
questa app ha un **decoder video integrato** (libVLC): il telefono/tablet si
collega **direttamente** alla telecamera in RTSP e fa tutto da solo — decodifica
il video, ascolta l'audio, rileva il movimento, muove la telecamera (PTZ) e
riproduce le ninna nanne.

## Cosa fa

- 🎥 **Video in diretta** dalla telecamera (RTSP via UDP, decoder libVLC).
- 👶 **Rilevamento movimento** sul dispositivo: confronta i fotogrammi e, quando
  il bambino si muove, mostra il messaggio **"Movimento rilevato"**, suona un
  **beep** e fa vibrare il dispositivo.
- 🔊 **Ascolto audio** della telecamera con un tocco (tasto altoparlante).
- 🕹️ **PTZ**: frecce su/giù/sinistra/destra per orientare la telecamera
  (ONVIF, come nella webapp).
- 🎵 **Ninna nanne**: riproduce i brani inclusi nell'app.
- 🌙 **Modalità notte** e **layout orizzontale** a schermo intero.
- ⚙️ **Configurazione guidata**: IP, utente, password e sensibilità.

## Struttura

```
flutter_app/
├── pubspec.yaml
├── lib/
│   ├── main.dart      # avvio + tema pastello, sceglie Setup o Home
│   ├── config.dart    # configurazione telecamera (salvata sul dispositivo)
│   ├── setup.dart     # schermata di configurazione
│   ├── home.dart      # schermata principale (video, movimento, PTZ, audio…)
│   ├── motion.dart    # rilevamento movimento (confronto fotogrammi)
│   └── onvif.dart     # controllo PTZ via ONVIF/SOAP
└── assets/
    ├── beep.wav       # suono dell'avviso movimento
    └── lullabies/     # metti qui i tuoi file .mp3 delle ninna nanne
```

## Come compilarla

> ⚠️ **Nota onesta:** io (l'assistente) non posso compilare né provare questa
> app: serve il **Flutter SDK** installato sul tuo computer, e per l'iPhone
> servono un **Mac con Xcode** e un account sviluppatore Apple. Qui sotto trovi
> i passaggi da fare tu.

### 1. Installa Flutter
Segui la guida ufficiale: https://docs.flutter.dev/get-started/install
Poi verifica con:
```bash
flutter doctor
```

### 2. Genera le cartelle di piattaforma
Questa cartella contiene solo il codice (`lib/`, `assets/`, `pubspec.yaml`).
Le cartelle `android/` e `ios/` si generano una volta sola con:
```bash
cd flutter_app
flutter create .
```
Questo comando **non** tocca i file già presenti in `lib/` e `assets/`.

### 3. Configura i permessi di rete (una volta sola)

**Android** — in `android/app/src/main/AndroidManifest.xml`, dentro
`<manifest …>` (fuori da `<application>`), aggiungi:
```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
```
e nel tag `<application …>` aggiungi `android:usesCleartextTraffic="true"`.

**iOS** — in `ios/Runner/Info.plist` aggiungi:
```xml
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsArbitraryLoads</key>
  <true/>
</dict>
<key>NSLocalNetworkUsageDescription</key>
<string>Serve per collegarsi alla telecamera sulla rete Wi-Fi locale.</string>
```

### 4. Aggiungi le ninna nanne (facoltativo)
Copia i tuoi file `.mp3` dentro `assets/lullabies/`. Compaiono da soli nella
lista dell'app (nessuna modifica al codice necessaria).

### 5. Scarica le dipendenze
```bash
flutter pub get
```

### 6a. Android (APK)
```bash
flutter build apk --release
```
L'APK finito è in `build/app/outputs/flutter-apk/app-release.apk`.
Copialo sul telefono e installalo (abilita "Origini sconosciute").
Oppure, con il telefono collegato via USB e il debug USB attivo:
```bash
flutter run --release
```

### 6b. iOS / iPad (serve un Mac)
```bash
flutter build ios --release
```
Poi apri `ios/Runner.xcworkspace` in **Xcode**, imposta il tuo *Team* di firma
e installa sul dispositivo (**Product → Run**). Per un iPhone/iPad personale è
sufficiente un Apple ID gratuito (l'app va rifirmata ogni 7 giorni).

## Permessi

L'app usa la rete locale (Wi-Fi) per raggiungere la telecamera. Su iOS, al
primo avvio, concedi il permesso di **rete locale**. Tieni telefono e
telecamera **sulla stessa rete Wi-Fi**.

## Primo avvio

1. Apri l'app → schermata **Configura la telecamera**.
2. Inserisci **IP** (es. `192.168.1.67`), **utente** (`admin`) e **password**.
3. Se serve, apri **Avanzate** per cambiare percorso RTSP (`onvif1`) e porte
   (RTSP `554`, ONVIF `5000`).
4. Regola la **sensibilità** del movimento e tocca **Salva e connetti**.

## Note tecniche

- **RTSP via UDP:** questa telecamera rifiuta il TCP, quindi il player usa UDP
  (nessun `--rtsp-tcp`) con buffer ridotto per limitare il ritardo.
- **Rilevamento movimento:** ogni ~700 ms l'app cattura uno snapshot dal player,
  lo riduce e lo confronta con il precedente (scala di grigi). Tutto in locale,
  **niente cloud, niente abbonamenti**.
- **PTZ:** stessa logica ONVIF della webapp (WS-Security UsernameToken, SOAP
  1.1/1.2 con fallback automatico).
- **Musica verso la telecamera:** questo modello **non** supporta l'audio in
  ingresso (backchannel ONVIF assente), quindi le ninna nanne si sentono dal
  dispositivo, non dalla telecamera. Vale sia qui che nella webapp.
