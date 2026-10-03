#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Despliega el firmware actualizado en la Pi
# =============================================================================
# Preserva config.json y data/perfiles/ (datos de producción en el dispositivo).
# Solo actualiza el código Python y los recursos estáticos (imágenes, etc.)
#
# USO:
#   cd firmware/deploy
#   ./deploy.sh 192.168.1.50
#   ./deploy.sh storymaker@192.168.1.50    # usuario alternativo
# =============================================================================

set -euo pipefail

DESTINO="${1:-}"

if [ -z "$DESTINO" ]; then
    echo "Uso: $0 [usuario@]<ip>"
    echo "Ejemplo: $0 192.168.1.50"
    echo "         $0 storymaker@192.168.1.50"
    exit 1
fi

# Añadir usuario por defecto si no se especificó
[[ "$DESTINO" == *@* ]] || DESTINO="storymaker@${DESTINO}"
IP="${DESTINO#*@}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRMWARE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PAQUETE="storymaker_deploy.tar.gz"
PROYECTO_REMOTO="/home/storymaker/proyecto"
CAPTIVE_SRC="${SCRIPT_DIR}/sistema/storymaker-captive.py"
SETPASS_SRC="${SCRIPT_DIR}/sistema/storymaker-setpass"
SUDOERS_SRC="${SCRIPT_DIR}/sistema/storymaker-shutdown"

echo "╔══════════════════════════════════════════╗"
echo "║      StoryMaker — Deploy                 ║"
echo "╠══════════════════════════════════════════╣"
printf "║  Destino: %-33s║\n" "${DESTINO}"
echo "╚══════════════════════════════════════════╝"
echo ""

# [0] Verificar que los ficheros de sistema existen en local
for F in "$CAPTIVE_SRC" "$SETPASS_SRC" "$SUDOERS_SRC"; do
    if [ ! -f "$F" ]; then
        echo "ERROR: no se encuentra ${F}"
        exit 1
    fi
done
echo ""

# [1] Empaquetar
echo "[1/6] Empaquetando firmware..."
tar -czf "/tmp/$PAQUETE" \
    -C "$FIRMWARE_DIR" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='./deploy' \
    --exclude='./data/config.json' \
    --exclude='./data/perfiles' \
    .

SIZE=$(du -h "/tmp/$PAQUETE" | cut -f1)
echo "      → $PAQUETE ($SIZE)"

# [2] Subir
echo "[2/6] Subiendo a la Pi..."
scp "/tmp/$PAQUETE" "${DESTINO}:/tmp/"
rm -f "/tmp/$PAQUETE"
echo "      → Subido"

# [3] Extraer
echo "[3/6] Extrayendo..."
ssh "$DESTINO" bash <<REMOTE
set -e
tar -xzf /tmp/${PAQUETE} -C ${PROYECTO_REMOTO}
rm -f /tmp/${PAQUETE}
echo "      → Extraído en ${PROYECTO_REMOTO}"
REMOTE

# [4] Desplegar portal cautivo
echo "[4/6] Actualizando storymaker-captive.py..."
scp "$CAPTIVE_SRC" "${DESTINO}:/tmp/storymaker-captive.py"
ssh "$DESTINO" "sudo cp /tmp/storymaker-captive.py /usr/local/bin/storymaker-captive.py && sudo systemctl restart storymaker-captive.service"
echo "      → Portal cautivo actualizado"

# [5] Ayudante de contraseña y permisos sudo
# El asistente de primer arranque necesita ambos para fijar la contraseña SSH
# propia del dispositivo. Se despliegan en cada deploy para que no se queden
# atrás en un equipo instalado con una versión anterior.
echo "[5/6] Actualizando storymaker-setpass y sudoers..."
scp "$SETPASS_SRC" "${DESTINO}:/tmp/storymaker-setpass"
scp "$SUDOERS_SRC" "${DESTINO}:/tmp/storymaker-shutdown"
ssh "$DESTINO" "sudo install -m 755 -o root -g root /tmp/storymaker-setpass /usr/local/bin/storymaker-setpass \
             && sudo install -m 440 -o root -g root /tmp/storymaker-shutdown /etc/sudoers.d/storymaker-shutdown \
             && rm -f /tmp/storymaker-setpass /tmp/storymaker-shutdown"
echo "      → Ayudante y permisos actualizados"

# [6] Reiniciar servicio principal
echo "[6/6] Reiniciando historias.service..."
ssh "$DESTINO" "sudo systemctl restart historias.service"
echo "      → Servicio reiniciado"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Deploy completado.                      ║"
echo "╚══════════════════════════════════════════╝"
