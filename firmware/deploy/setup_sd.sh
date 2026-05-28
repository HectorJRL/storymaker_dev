#!/usr/bin/env bash
# =============================================================================
# setup_sd.sh — Configura una Pi OS Lite 64-bit Bookworm limpia para StoryMaker
# =============================================================================
#
# PREREQUISITOS — en Raspberry Pi Imager antes de flashear:
#   • Modelo:     Raspberry Pi Zero 2W
#   • SO:         Raspberry Pi OS Lite (64-bit, Bookworm)
#   • Hostname:   storymaker
#   • Usuario:    storymaker
#   • SSH:        activado
#   • WiFi:       tu red local (solo para el setup; la imagen final arranca en AP)
#
# USO:
#   cd firmware/deploy
#   ./setup_sd.sh 192.168.1.50
#   ./setup_sd.sh 192.168.1.50 ~/.ssh/mi_clave.pub    # clave alternativa
#
# PRIMERA CONEXIÓN: si no añadiste tu clave SSH en Imager, el script pedirá
# la contraseña de storymaker una sola vez (paso 0). Después todo es automático.
# =============================================================================

set -euo pipefail

IP="${1:-}"
PUBKEY_LOCAL="${2:-${HOME}/.ssh/storymaker_dev.pub}"
PI="storymaker@${IP}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRMWARE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SISTEMA_DIR="${SCRIPT_DIR}/sistema"

# ── Validaciones ──────────────────────────────────────────────────────────────
if [ -z "$IP" ]; then
    echo "Uso: $0 <ip_de_la_pi> [clave_publica.pub]"
    echo "Ejemplo: $0 192.168.1.50"
    exit 1
fi

if [ ! -f "$PUBKEY_LOCAL" ]; then
    echo "ERROR: clave pública no encontrada: $PUBKEY_LOCAL"
    echo "Genera una con: ssh-keygen -t ed25519 -f ~/.ssh/storymaker_dev"
    exit 1
fi

for f in historias.service storymaker-wifi.service storymaker-captive.service \
          storymaker-wifi.sh storymaker-captive.py storymaker-shutdown; do
    if [ ! -f "$SISTEMA_DIR/$f" ]; then
        echo "ERROR: falta $SISTEMA_DIR/$f"
        exit 1
    fi
done

echo "╔══════════════════════════════════════════════╗"
echo "║      StoryMaker — Setup de SD nueva          ║"
echo "╠══════════════════════════════════════════════╣"
printf "║  Pi:      %-35s║\n" "${IP}"
printf "║  Clave:   %-35s║\n" "$(basename "$PUBKEY_LOCAL")"
printf "║  Firmware:%-35s║\n" "$(basename "$FIRMWARE_DIR")"
echo "╚══════════════════════════════════════════════╝"
echo ""

# =============================================================================
# PASO 0 — Acceso SSH por clave (una sola vez con contraseña si hace falta)
# =============================================================================
echo "[0/8] Configurando acceso SSH por clave..."
ssh-copy-id -i "$PUBKEY_LOCAL" "$PI"
echo "      → Listo"

# =============================================================================
# PASO 1 — Paquetes del sistema
# =============================================================================
echo ""
echo "[1/8] Instalando paquetes del sistema..."
echo "      (puede tardar varios minutos en el Zero 2W)"

ssh "$PI" bash <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

sudo apt-get update -qq
sudo apt-get upgrade -y -qq

# Paquetes Python del sistema (se acceden desde el venv via --system-site-packages)
# y herramientas de audio, tipografía y red
sudo apt-get install -y -qq \
    python3-pip python3-venv python3-dev \
    python3-rpi.gpio python3-spidev \
    python3-serial python3-flask \
    python3-pil python3-qrcode \
    mpg123 espeak-ng \
    avahi-daemon \
    fonts-dejavu-core \
    alsa-utils \
    netfilter-persistent iptables-persistent

echo "      → Paquetes instalados"
REMOTE

# =============================================================================
# PASO 2 — Hardware: SPI, UART, I2S y grupos de usuario
# =============================================================================
echo ""
echo "[2/8] Habilitando hardware (SPI, UART, I2S)..."

ssh "$PI" bash <<'REMOTE'
set -euo pipefail
CONFIG=/boot/firmware/config.txt
CMDLINE=/boot/firmware/cmdline.txt

# SPI — pantalla e-ink (GPIO 8/10/11)
grep -q "^dtparam=spi=on" "$CONFIG" \
    || echo "dtparam=spi=on" | sudo tee -a "$CONFIG" > /dev/null

# UART estable para impresora — deshabilitar Bluetooth libera el PL011 para GPIO14/15
grep -q "^enable_uart=1" "$CONFIG" \
    || echo "enable_uart=1" | sudo tee -a "$CONFIG" > /dev/null
grep -q "^dtoverlay=disable-bt" "$CONFIG" \
    || echo "dtoverlay=disable-bt" | sudo tee -a "$CONFIG" > /dev/null

# I2S audio — MAX98357A (GPIO 18/19/21)
grep -q "^dtoverlay=hifiberry-dac" "$CONFIG" \
    || echo "dtoverlay=hifiberry-dac" | sudo tee -a "$CONFIG" > /dev/null

# Quitar consola serie de cmdline para dejar el UART libre a la impresora
sudo sed -i 's/console=serial0,[0-9]* //g' "$CMDLINE"
sudo sed -i 's/console=ttyAMA0,[0-9]* //g' "$CMDLINE"

# Grupos de hardware
sudo usermod -aG spi,gpio,dialout,audio storymaker

echo "      → Hardware configurado"
REMOTE

# =============================================================================
# PASO 3 — Red: NetworkManager y perfil AP
# =============================================================================
echo ""
echo "[3/8] Configurando red y perfil AP..."

ssh "$PI" bash <<'REMOTE'
set -euo pipefail

# Arranque más rápido: no esperar a que la red conecte
sudo systemctl disable NetworkManager-wait-online.service 2>/dev/null || true

# Perfil AP abierto "StoryMaker-Setup" en 10.42.0.1
# Este es el punto de acceso que se activa cuando no hay WiFi conocida
if nmcli connection show "StoryMaker-Setup" &>/dev/null; then
    echo "      → Perfil AP ya existía (sin cambios)"
else
    sudo nmcli connection add \
        type wifi \
        con-name "StoryMaker-Setup" \
        ifname wlan0 \
        ssid "StoryMaker-Setup" \
        mode ap \
        ipv4.method shared \
        ipv4.addresses "10.42.0.1/24" \
        802-11-wireless.band bg \
        802-11-wireless.channel 6 \
        connection.autoconnect no
    echo "      → Perfil AP creado"
fi
REMOTE

# =============================================================================
# PASO 4 — iptables: captive portal HTTP→8080
# =============================================================================
echo ""
echo "[4/8] Configurando iptables para captive portal..."

ssh "$PI" bash <<'REMOTE'
set -euo pipefail

# Redirigir HTTP (80) → portal cautivo Flask (8080) en modo AP
# Sin esta regla iOS/Android/Windows no detectan el captive portal
if ! sudo iptables -t nat -C PREROUTING -i wlan0 -p tcp --dport 80 \
        -j REDIRECT --to-port 8080 2>/dev/null; then
    sudo iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 \
        -j REDIRECT --to-port 8080
fi
sudo netfilter-persistent save

echo "      → Reglas guardadas con netfilter-persistent"
REMOTE

# =============================================================================
# PASO 5 — ALSA: device "plug:dmixed" para MAX98357A
# =============================================================================
echo ""
echo "[5/8] Configurando ALSA..."

ssh "$PI" bash <<'REMOTE'
set -euo pipefail

sudo tee /etc/asound.conf > /dev/null <<'ASOUND'
# StoryMaker — MAX98357A I2S via hifiberry-dac (Pi Zero 2W, card 0)
# type dmix: mixer por software que permite streams simultáneos.
# Necesario para que el hilo keep-alive (aplay /dev/zero) y mpg123
# usen el dispositivo al mismo tiempo sin conflicto, eliminando el
# chasquido del MAX98357A en cada premisa.
pcm.dmixed {
    type dmix
    ipc_key 1024
    ipc_key_add_uid true
    slave {
        pcm "hw:0,0"
        rate 44100
        format S16_LE
        period_time 0
        period_size 1024
        buffer_size 8192
    }
    bindings {
        0 0
        1 1
    }
}
ctl.dmixed {
    type hw
    card 0
}
ASOUND

echo "      → /etc/asound.conf creado"
REMOTE

# =============================================================================
# PASO 6 — Archivos de sistema: servicios, scripts, sudoers
# =============================================================================
echo ""
echo "[6/8] Instalando servicios y scripts del sistema..."

scp "$SISTEMA_DIR/historias.service"          "${PI}:/tmp/"
scp "$SISTEMA_DIR/storymaker-wifi.service"    "${PI}:/tmp/"
scp "$SISTEMA_DIR/storymaker-captive.service" "${PI}:/tmp/"
scp "$SISTEMA_DIR/storymaker-wifi.sh"         "${PI}:/tmp/"
scp "$SISTEMA_DIR/storymaker-captive.py"      "${PI}:/tmp/"
scp "$SISTEMA_DIR/storymaker-shutdown"        "${PI}:/tmp/"

ssh "$PI" bash <<'REMOTE'
set -euo pipefail

sudo mv /tmp/historias.service          /etc/systemd/system/
sudo mv /tmp/storymaker-wifi.service    /etc/systemd/system/
sudo mv /tmp/storymaker-captive.service /etc/systemd/system/
sudo mv /tmp/storymaker-wifi.sh         /usr/local/bin/
sudo mv /tmp/storymaker-captive.py      /usr/local/bin/
sudo chmod +x /usr/local/bin/storymaker-wifi.sh
sudo chmod +x /usr/local/bin/storymaker-captive.py
sudo install -m 440 -o root -g root /tmp/storymaker-shutdown /etc/sudoers.d/storymaker-shutdown

sudo systemctl daemon-reload
sudo systemctl enable avahi-daemon
sudo systemctl enable storymaker-wifi.service
sudo systemctl enable storymaker-captive.service
sudo systemctl enable historias.service

echo "      → Servicios instalados y habilitados"
REMOTE

# =============================================================================
# PASO 7 — Entorno Python (venv + edge-tts)
# =============================================================================
echo ""
echo "[7/8] Preparando entorno Python..."

ssh "$PI" bash <<'REMOTE'
set -euo pipefail

mkdir -p /home/storymaker/proyecto
cd /home/storymaker/proyecto

# Venv con acceso a paquetes del sistema (RPi.GPIO, spidev, Flask, Pillow, etc.)
# Solo necesitamos pip para edge-tts, que no está en los repos de Debian
python3 -m venv --system-site-packages venv

venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet edge-tts

echo "      → Venv listo (edge-tts instalado)"
REMOTE

# =============================================================================
# PASO 8 — Primer despliegue del firmware
# =============================================================================
echo ""
echo "[8/8] Desplegando firmware..."

PAQUETE="storymaker_setup.tar.gz"

# En el setup inicial sí desplegamos config.json y perfiles/ (primera vez)
tar -czf "/tmp/$PAQUETE" \
    -C "$FIRMWARE_DIR" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='./deploy' \
    .

SIZE=$(du -h "/tmp/$PAQUETE" | cut -f1)
echo "      → Paquete: $PAQUETE ($SIZE)"

scp "/tmp/$PAQUETE" "${PI}:/tmp/"
rm -f "/tmp/$PAQUETE"

ssh "$PI" bash <<REMOTE
set -e
tar -xzf /tmp/${PAQUETE} -C /home/storymaker/proyecto
rm -f /tmp/${PAQUETE}
echo "      → Firmware extraído"
REMOTE

# =============================================================================
# Verificación final
# =============================================================================
echo ""
echo "Verificando instalación..."
ssh "$PI" bash <<'REMOTE'
OK=0; FAIL=0

check() {
    if eval "$2" &>/dev/null; then
        echo "    ✓ $1"; OK=$((OK+1))
    else
        echo "    ✗ $1  ← FALTA"; FAIL=$((FAIL+1))
    fi
}

echo "  Servicios:"
check "historias.service habilitado"         "systemctl is-enabled historias.service"
check "storymaker-wifi.service habilitado"   "systemctl is-enabled storymaker-wifi.service"
check "storymaker-captive.service habilitado""systemctl is-enabled storymaker-captive.service"
check "avahi-daemon habilitado"              "systemctl is-enabled avahi-daemon"

echo "  Archivos:"
check "main.py"               "test -f /home/storymaker/proyecto/main.py"
check "config.json"           "test -f /home/storymaker/proyecto/data/config.json"
check "venv/python3"          "test -f /home/storymaker/proyecto/venv/bin/python3"
check "edge-tts"              "test -f /home/storymaker/proyecto/venv/bin/edge-tts"
check "storymaker-wifi.sh"    "test -f /usr/local/bin/storymaker-wifi.sh"
check "storymaker-captive.py" "test -f /usr/local/bin/storymaker-captive.py"
check "sudoers"               "test -f /etc/sudoers.d/storymaker-shutdown"
check "asound.conf"           "test -f /etc/asound.conf"

echo ""
echo "  Resultado: $OK OK, $FAIL fallos"
[ "$FAIL" -eq 0 ] || echo "  ⚠ Revisa los fallos antes de continuar"
REMOTE

echo ""
echo "Reiniciando la Pi..."
echo "(necesario para activar SPI, UART e I2S desde config.txt)"
ssh "$PI" "sudo reboot" || true

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Setup completado. La Pi está reiniciando.          ║"
echo "║                                                      ║"
echo "║  Tras el reinicio (~30s), accede al portal en:      ║"
printf "║    http://storymaker.local:5000%-22s║\n" " "
printf "║    http://${IP}:5000%-$((35 - ${#IP}))s║\n" " "
echo "║                                                      ║"
echo "║  Para deploys futuros:                              ║"
printf "║    ./deploy.sh %-38s║\n" "${IP}"
echo "╚══════════════════════════════════════════════════════╝"
