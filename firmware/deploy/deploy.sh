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

echo "╔══════════════════════════════════════════╗"
echo "║      StoryMaker — Deploy                 ║"
echo "╠══════════════════════════════════════════╣"
printf "║  Destino: %-33s║\n" "${DESTINO}"
echo "╚══════════════════════════════════════════╝"
echo ""

# [1] Empaquetar
echo "[1/4] Empaquetando firmware..."
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
echo "[2/4] Subiendo a la Pi..."
scp "/tmp/$PAQUETE" "${DESTINO}:/tmp/"
rm -f "/tmp/$PAQUETE"
echo "      → Subido"

# [3] Extraer
echo "[3/4] Extrayendo..."
ssh "$DESTINO" bash <<REMOTE
set -e
tar -xzf /tmp/${PAQUETE} -C ${PROYECTO_REMOTO}
rm -f /tmp/${PAQUETE}
echo "      → Extraído en ${PROYECTO_REMOTO}"
REMOTE

# [4] Reiniciar servicio
echo "[4/4] Reiniciando historias.service..."
ssh "$DESTINO" "sudo systemctl restart historias.service"
echo "      → Servicio reiniciado"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Deploy completado.                      ║"
echo "╚══════════════════════════════════════════╝"
