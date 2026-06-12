#!/usr/bin/env bash
# =============================================================================
# crear_imagen.sh — Genera la imagen distributable de StoryMaker
# =============================================================================
#
# FLUJO:
#   1. Limpia la Pi vía SSH (limpiar_pi.sh)
#   2. Apaga la Pi
#   3. El usuario inserta la SD en este ordenador
#   4. Captura imagen con dd
#   5. Reduce la imagen con pishrink.sh
#   6. Comprime con xz
#
# PREREQUISITOS en este ordenador:
#   pishrink.sh en PATH:
#     wget https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh
#     chmod +x pishrink.sh && sudo mv pishrink.sh /usr/local/bin/
#
# USO:
#   cd firmware/deploy
#   ./crear_imagen.sh <ip-de-la-pi>
#   ./crear_imagen.sh 192.168.1.50
# =============================================================================

set -euo pipefail

IP="${1:-}"
if [ -z "$IP" ]; then
    echo "Uso: $0 <ip-de-la-pi>"
    echo "Ejemplo: $0 192.168.1.50"
    exit 1
fi

if ! command -v pishrink.sh &>/dev/null; then
    echo "ERROR: pishrink.sh no encontrado en PATH."
    echo ""
    echo "  wget https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh"
    echo "  chmod +x pishrink.sh && sudo mv pishrink.sh /usr/local/bin/"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI="storymaker@${IP}"
FECHA=$(date +%Y-%m-%d)
NOMBRE="storymaker-${FECHA}.img"
DESTINO="${SCRIPT_DIR}/../../${NOMBRE}.xz"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  StoryMaker — Creación de imagen distributable       ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Pi:     %-43s║\n" "${IP}"
printf "║  Imagen: %-43s║\n" "${NOMBRE}.xz"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── [1/4] Limpiar Pi ─────────────────────────────────────────────────
echo "[1/4] Limpiando Pi..."
ssh "$PI" 'bash -s' < "${SCRIPT_DIR}/limpiar_pi.sh"
echo ""

# ── [2/4] Apagar Pi ──────────────────────────────────────────────────
echo "[2/4] Apagando Pi..."
ssh "$PI" "sudo shutdown -h now" 2>/dev/null || true
echo "      Esperando 25 s a que la Pi se apague..."
sleep 25
echo "      → Hecho"
echo ""

# ── [3/4] Capturar imagen ────────────────────────────────────────────
echo "[3/4] Captura de imagen"
echo "      ▸ Extrae la SD de la Pi"
echo "      ▸ Insértala en este ordenador"
echo ""
echo "  Dispositivos detectados:"
lsblk -o NAME,SIZE,LABEL,MOUNTPOINT | grep -v loop || true
echo ""
read -r -p "  Ruta del dispositivo SD (ej. /dev/sdb, /dev/mmcblk0): " SD_DEV

if [ ! -b "$SD_DEV" ]; then
    echo "ERROR: ${SD_DEV} no es un dispositivo de bloque válido."
    exit 1
fi

# Desmontar particiones si están montadas
for PART in "${SD_DEV}"?* "${SD_DEV}"p?* 2>/dev/null; do
    [ -b "$PART" ] || continue
    MPOINT=$(lsblk -o MOUNTPOINT -n "$PART" 2>/dev/null | head -1 || true)
    if [ -n "$MPOINT" ] && [ "$MPOINT" != " " ]; then
        echo "      Desmontando ${PART}..."
        sudo umount "$PART" 2>/dev/null || true
    fi
done

echo "      Leyendo SD → /tmp/${NOMBRE} (puede tardar varios minutos)..."
sudo dd if="$SD_DEV" of="/tmp/${NOMBRE}" bs=4M status=progress conv=fsync
echo "      → Imagen capturada"
echo ""

# ── [4/4] Reducir y comprimir ────────────────────────────────────────
echo "[4/4] Reduciendo con pishrink.sh..."
sudo pishrink.sh -Za "/tmp/${NOMBRE}"

# pishrink con -Za ya comprime con xz y añade .xz
FINAL_XZ="/tmp/${NOMBRE}.xz"
if [ ! -f "$FINAL_XZ" ]; then
    # Fallback: comprimir manualmente si pishrink no usó -a
    echo "      Comprimiendo con xz..."
    xz -9 -T0 "/tmp/${NOMBRE}"
    FINAL_XZ="/tmp/${NOMBRE}.xz"
fi

SIZE=$(du -h "$FINAL_XZ" | cut -f1)
cp "$FINAL_XZ" "$DESTINO"
sudo rm -f "/tmp/${NOMBRE}" "/tmp/${NOMBRE}.xz"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Imagen lista.                                       ║"
printf "║  Archivo: %-43s║\n" "${NOMBRE}.xz"
printf "║  Tamaño:  %-43s║\n" "$SIZE"
echo "║                                                      ║"
echo "║  Siguiente paso — subir a Codeberg Releases:         ║"
echo "║    Release: vYYYY-MM-DD                              ║"
printf "║    Asset:   %-40s║\n" "${NOMBRE}.xz"
echo "╚══════════════════════════════════════════════════════╝"
