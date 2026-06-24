#!/usr/bin/env bash
# =============================================================================
# crear_imagen.sh — Genera la imagen distributable de StoryMaker
# =============================================================================
#
# FLUJO NORMAL (con IP de la Pi):
#   1. Limpia la Pi vía SSH (limpiar_pi.sh)
#   2. Apaga la Pi
#   3. El usuario inserta la SD en este ordenador
#   4. Captura imagen con dd
#   5. Reduce la imagen con pishrink.sh
#   6. Comprime con xz
#
# FLUJO LOCAL (SD ya conectada, Pi ya apagada):
#   ./crear_imagen.sh --local
#   Salta los pasos 1 y 2 (SSH) y va directo al dd.
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
#   ./crear_imagen.sh --local
# =============================================================================

set -euo pipefail

ARG="${1:-}"
if [ -z "$ARG" ]; then
    echo "Uso: $0 <ip-de-la-pi>"
    echo "     $0 --local   (SD ya conectada, Pi ya apagada)"
    exit 1
fi

LOCAL=false
if [ "$ARG" = "--local" ]; then
    LOCAL=true
    IP="(local)"
else
    IP="$ARG"
fi

if ! command -v pishrink.sh &>/dev/null; then
    echo "ERROR: pishrink.sh no encontrado en PATH."
    echo ""
    echo "  wget https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh"
    echo "  chmod +x pishrink.sh && sudo mv pishrink.sh /usr/local/bin/"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

if [ "$LOCAL" = false ]; then
    PI="storymaker@${IP}"

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
else
    echo "[1/4] Limpieza y apagado Pi — omitidos (modo --local)"
    echo ""
fi

# ── [3/4] Capturar imagen ────────────────────────────────────────────
echo "[3/4] Captura de imagen"
if [ "$LOCAL" = false ]; then
    echo "      ▸ Extrae la SD de la Pi"
    echo "      ▸ Insértala en este ordenador"
    echo ""
fi
echo "  Dispositivos detectados:"
lsblk -o NAME,SIZE,LABEL,MOUNTPOINT | grep -v loop || true
echo ""
read -r -p "  Ruta del dispositivo SD (ej. /dev/sdb, /dev/mmcblk0): " SD_DEV

if [ ! -b "$SD_DEV" ]; then
    echo "ERROR: ${SD_DEV} no es un dispositivo de bloque válido."
    exit 1
fi

# Desmontar particiones si están montadas
for PART in "${SD_DEV}"?* "${SD_DEV}"p?*; do
    [ -b "$PART" ] || continue
    MPOINT=$(lsblk -o MOUNTPOINT -n "$PART" 2>/dev/null | head -1 || true)
    if [ -n "$MPOINT" ] && [ "$MPOINT" != " " ]; then
        echo "      Desmontando ${PART}..."
        sudo umount "$PART" 2>/dev/null || true
    fi
done

# En modo local: montar root, limpiar, desmontar (sustituye a SSH)
if [ "$LOCAL" = true ]; then
    echo ""
    echo "      Limpiando FS directamente sobre la SD..."
    # Calcular nombre de la partición raíz (sdc2 o mmcblk0p2)
    if [[ "$SD_DEV" =~ [0-9]$ ]]; then
        ROOT_PART="${SD_DEV}p2"
    else
        ROOT_PART="${SD_DEV}2"
    fi
    ROOTFS=$(mktemp -d /tmp/storymaker-root-XXXXXX)
    sudo mount "$ROOT_PART" "$ROOTFS"
    sudo bash "${SCRIPT_DIR}/limpiar_montada.sh" "$ROOTFS"
    sudo umount "$ROOTFS"
    rmdir "$ROOTFS"

    # Encoger el ext4 al mínimo para que dd solo lea datos reales
    echo "      Pre-encogiendo partición raíz en la SD..."
    sudo e2fsck -f "$ROOT_PART"
    sudo resize2fs -M "$ROOT_PART"
    NEW_BYTES=$(sudo dumpe2fs -h "$ROOT_PART" 2>/dev/null \
        | awk '/Block count:/{bc=$3} /Block size:/{bs=$3} END{print bc*bs}')
    START_SECTOR=$(sudo sfdisk -d "$SD_DEV" \
        | grep "$ROOT_PART" | grep -oP 'start=\s*\K[0-9]+')
    NEW_SECTORS=$(( (NEW_BYTES + 511) / 512 ))
    NEW_END=$(( START_SECTOR + NEW_SECTORS - 1 ))
    echo "${START_SECTOR},${NEW_SECTORS}" | sudo sfdisk --no-reread --force -N 2 "$SD_DEV" >/dev/null
    echo "      → Partición raíz encogida a $(( NEW_BYTES / 1024 / 1024 )) MB"
    echo ""
fi

WORK_DIR="${HOME}"

# Leer solo hasta el final de la última partición, no la SD entera
LAST_SECTOR=$(sudo sfdisk -d "$SD_DEV" \
    | awk -F'[= ,]+' '/start=/{s=$4; sz=$6; e=s+sz-1; if(e>max)max=e} END{print max}')
if [ -z "$LAST_SECTOR" ] || [ "$LAST_SECTOR" -le 0 ] 2>/dev/null; then
    echo "AVISO: no se pudo calcular el último sector; leyendo la SD completa."
    LAST_SECTOR=""
fi

if [ -n "$LAST_SECTOR" ]; then
    TOTAL_BYTES=$(( (LAST_SECTOR + 1) * 512 ))
    BLOCK_4M=$(( 4 * 1024 * 1024 ))
    DD_COUNT=$(( (TOTAL_BYTES + BLOCK_4M - 1) / BLOCK_4M ))
    SD_TOTAL=$(lsblk -bno SIZE "$SD_DEV" | head -1)
    echo "      Datos útiles: $(( TOTAL_BYTES / 1024 / 1024 )) MB  (SD completa: $(( SD_TOTAL / 1024 / 1024 / 1024 )) GB)"
    echo "      Leyendo SD → ${WORK_DIR}/${NOMBRE}..."
    sudo dd if="$SD_DEV" of="${WORK_DIR}/${NOMBRE}" bs=4M count="$DD_COUNT" status=progress conv=fsync
else
    echo "      Leyendo SD → ${WORK_DIR}/${NOMBRE} (SD completa, puede tardar mucho)..."
    sudo dd if="$SD_DEV" of="${WORK_DIR}/${NOMBRE}" bs=4M status=progress conv=fsync
fi
echo "      → Imagen capturada"
echo ""

# ── [4/4] Reducir y comprimir ────────────────────────────────────────
echo "[4/4] Reduciendo con pishrink.sh..."
sudo pishrink.sh -Za "${WORK_DIR}/${NOMBRE}"

# pishrink con -Za ya comprime con xz y añade .xz
FINAL_XZ="${WORK_DIR}/${NOMBRE}.xz"
if [ ! -f "$FINAL_XZ" ]; then
    # Fallback: comprimir manualmente si pishrink no usó -a
    echo "      Comprimiendo con xz..."
    xz -9 -T0 "${WORK_DIR}/${NOMBRE}"
    FINAL_XZ="${WORK_DIR}/${NOMBRE}.xz"
fi

# Verificar que el .xz existe y tiene tamaño razonable antes de seguir
if [ ! -s "$FINAL_XZ" ]; then
    echo "ERROR: ${FINAL_XZ} no existe o está vacío. Abortando — la imagen original no se borra."
    exit 1
fi
XZ_BYTES=$(stat -c%s "$FINAL_XZ")
if [ "$XZ_BYTES" -lt 104857600 ]; then
    echo "ERROR: ${FINAL_XZ} es sospechosamente pequeño ($(du -h "$FINAL_XZ" | cut -f1)). Abortando."
    exit 1
fi

SIZE=$(du -h "$FINAL_XZ" | cut -f1)
cp "$FINAL_XZ" "$DESTINO"

# Verificar que la copia en destino coincide en tamaño antes de borrar
DEST_BYTES=$(stat -c%s "$DESTINO")
if [ "$XZ_BYTES" -ne "$DEST_BYTES" ]; then
    echo "ERROR: el fichero copiado no coincide en tamaño con el original."
    echo "       Original: ${XZ_BYTES} bytes  |  Destino: ${DEST_BYTES} bytes"
    echo "       Abortando — la imagen original no se borra."
    exit 1
fi

sudo rm -f "${WORK_DIR}/${NOMBRE}" "${WORK_DIR}/${NOMBRE}.xz"

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
