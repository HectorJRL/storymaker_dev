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
#   ./deploy.sh storymaker@192.168.1.50       # usuario alternativo
#   ./deploy.sh --solo-firmware 192.168.1.50  # omite los ficheros de sistema
#
# SOBRE LA CONTRASEÑA DE sudo:
#   Las imágenes a partir de v2026-10-03 ya no traen el `NOPASSWD: ALL` que
#   Raspberry Pi OS instala de serie, así que instalar ficheros de sistema exige
#   la contraseña del dispositivo. Ese paso usa `ssh -t` para que sudo tenga
#   terminal donde pedirla; sin -t falla con «a terminal is required».
#   Reiniciar historias.service sí está en la lista corta de /etc/sudoers.d, por
#   eso no necesita terminal.
#
#   Con --solo-firmware se omite el paso privilegiado. Sirve cuando sólo ha
#   cambiado código Python, que es el caso habitual: comprueba antes con
#   `git diff --name-only <tag-de-la-imagen>..HEAD -- firmware/deploy/sistema/`
#   que no haya cambios ahí.
# =============================================================================

set -euo pipefail

SOLO_FIRMWARE=false
DESTINO=""
for ARG in "$@"; do
    case "$ARG" in
        --solo-firmware) SOLO_FIRMWARE=true ;;
        -*)              echo "Opción no reconocida: $ARG"; exit 1 ;;
        *)               DESTINO="$ARG" ;;
    esac
done

if [ -z "$DESTINO" ]; then
    echo "Uso: $0 [--solo-firmware] [usuario@]<ip>"
    echo "Ejemplo: $0 192.168.1.50"
    echo "         $0 storymaker@192.168.1.50"
    echo "         $0 --solo-firmware 192.168.1.50"
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
echo "[1/5] Empaquetando firmware..."
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
echo "[2/5] Subiendo a la Pi..."
scp "/tmp/$PAQUETE" "${DESTINO}:/tmp/"
rm -f "/tmp/$PAQUETE"
echo "      → Subido"

# [3] Extraer
echo "[3/5] Extrayendo..."
ssh "$DESTINO" bash <<REMOTE
set -e
tar -xzf /tmp/${PAQUETE} -C ${PROYECTO_REMOTO}
rm -f /tmp/${PAQUETE}
echo "      → Extraído en ${PROYECTO_REMOTO}"
REMOTE

# [4] Ficheros de sistema: captivo, ayudante de contraseña y sudoers
# Van juntos y en una sola sesión `ssh -t`, para que sudo pida la contraseña una
# única vez y su caché cubra el resto de órdenes. Antes esto eran tres `ssh`
# sueltos sin terminal, que desde que la imagen no trae NOPASSWD: ALL fallan con
# «sudo: a terminal is required to read the password».
if [ "$SOLO_FIRMWARE" = true ]; then
    echo "[4/5] Ficheros de sistema — omitidos (--solo-firmware)"
else
    echo "[4/5] Instalando ficheros de sistema (sudo pedirá la contraseña del dispositivo)..."
    scp "$CAPTIVE_SRC" "${DESTINO}:/tmp/storymaker-captive.py"
    scp "$SETPASS_SRC" "${DESTINO}:/tmp/storymaker-setpass"
    scp "$SUDOERS_SRC" "${DESTINO}:/tmp/storymaker-shutdown"
    # El sudoers se valida ANTES de instalarlo: un fichero malformado en
    # /etc/sudoers.d deja el dispositivo sin sudo de ningún tipo.
    ssh -t "$DESTINO" "sudo sh -c '
        set -e
        visudo -c -f /tmp/storymaker-shutdown
        install -m 755 -o root -g root /tmp/storymaker-captive.py /usr/local/bin/storymaker-captive.py
        install -m 755 -o root -g root /tmp/storymaker-setpass    /usr/local/bin/storymaker-setpass
        install -m 440 -o root -g root /tmp/storymaker-shutdown   /etc/sudoers.d/storymaker-shutdown
        systemctl restart storymaker-captive.service
    ' ; rm -f /tmp/storymaker-captive.py /tmp/storymaker-setpass /tmp/storymaker-shutdown"
    echo "      → Captivo, ayudante y permisos actualizados"
fi

# [5] Reiniciar servicio principal
# Esta orden sí está en /etc/sudoers.d/storymaker-shutdown, así que no necesita
# terminal ni contraseña.
echo "[5/5] Reiniciando historias.service..."
ssh "$DESTINO" "sudo -n systemctl restart historias.service"
echo "      → Servicio reiniciado"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Deploy completado.                      ║"
echo "╚══════════════════════════════════════════╝"
