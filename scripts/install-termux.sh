#!/data/data/com.termux/files/usr/bin/bash
# Installer "un comando" per Baby Monitor su Android (Termux).
# Uso, dentro Termux:
#   bash scripts/install-termux.sh
# Se non hai ancora scaricato il progetto, prima:
#   pkg install -y git && git clone <URL-REPO> Babymonitor && cd Babymonitor
#
# Fa tutto: dipendenze (OpenCV via pkg, non pip), configurazione base,
# wake-lock e avvio automatico al riavvio (Termux:Boot).

set -e
echo "==> Baby Monitor - installazione su Termux"

if [ ! -d "$PREFIX" ] || [ -z "$PREFIX" ]; then
  echo "ATTENZIONE: questo script va eseguito dentro Termux."
fi

echo "==> Aggiorno i pacchetti..."
pkg update -y && pkg upgrade -y

echo "==> Installo Python, OpenCV e git..."
# IMPORTANTE: su Android OpenCV si installa col pacchetto di Termux, NON con pip.
pkg install -y python opencv-python git

echo "==> Installo Flask, PyYAML e qrcode..."
pip install --upgrade pip >/dev/null 2>&1 || true
pip install flask pyyaml qrcode

echo "==> Permesso di accesso alla memoria (per le ninna nanne)..."
termux-setup-storage || true

# Cartella del progetto: quella corrente se contiene run.py, altrimenti ~/Babymonitor
if [ -f "run.py" ]; then
  APP_DIR="$(pwd)"
else
  APP_DIR="$HOME/Babymonitor"
fi
echo "==> Cartella progetto: $APP_DIR"

# Config di base (la configurazione vera si fa poi dal WIZARD nell'app)
if [ ! -f "$APP_DIR/config.yaml" ] && [ -f "$APP_DIR/config.example.yaml" ]; then
  cp "$APP_DIR/config.example.yaml" "$APP_DIR/config.yaml"
  echo "==> Creato config.yaml (lo completerai dal wizard nell'app)."
fi

# Avvio automatico al riavvio del telefono (richiede l'app Termux:Boot)
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"
cat > "$BOOT_DIR/babymonitor.sh" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd "$APP_DIR"
python run.py
EOF
chmod +x "$BOOT_DIR/babymonitor.sh"
echo "==> Avvio automatico configurato (installa l'app 'Termux:Boot' da F-Droid)."

echo ""
echo "============================================================"
echo " Installazione completata! 🎉"
echo ""
echo " Per avviare ORA:"
echo "     termux-wake-lock"
echo "     cd $APP_DIR && python run.py"
echo ""
echo " Poi dall'iPad/telefono (stessa rete WiFi) apri l'indirizzo"
echo " mostrato e segui il WIZARD per configurare la camera."
echo ""
echo " Ricorda le impostazioni MIUI (Xiaomi): Autostart ON,"
echo " batteria 'Nessuna restrizione', blocca Termux nei recenti."
echo "============================================================"
