#!/usr/bin/env bash
# =============================================================================
# limpiar_montada.sh — Limpieza para imagen distributable sobre FS montado
# =============================================================================
# Equivalente a limpiar_pi.sh pero sin requerir la Pi encendida.
# Opera directamente sobre la partición raíz montada en el PC.
#
# USO (llamado desde crear_imagen.sh, no directamente):
#   sudo bash limpiar_montada.sh <punto-de-montaje>
# =============================================================================

set -euo pipefail

ROOTFS="${1:?Uso: $0 <punto-de-montaje>}"

if [ ! -d "${ROOTFS}/etc" ]; then
    echo "ERROR: ${ROOTFS} no parece un sistema de ficheros raíz de Linux."
    exit 1
fi

echo "╔══════════════════════════════════════════════════════╗"
echo "║  StoryMaker — Limpieza sobre FS montado              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── [1] Perfiles WiFi de cliente ─────────────────────────────────────
echo "[1/6] Borrando perfiles WiFi de cliente..."
NM_DIR="${ROOTFS}/etc/NetworkManager/system-connections"
if [ -d "$NM_DIR" ]; then
    for CONN in "${NM_DIR}"/*.nmconnection; do
        [ -f "$CONN" ] || continue
        if ! grep -q 'mode=ap' "$CONN"; then
            echo "      Borrando: $(basename "$CONN")"
            rm -f "$CONN"
        fi
    done
fi
echo "      → Hecho"

# ── [2] Limpiar config.json ──────────────────────────────────────────
echo "[2/6] Limpiando config.json..."
CONFIG="${ROOTFS}/home/storymaker/proyecto/data/config.json"
if [ -f "$CONFIG" ]; then
    python3 - "$CONFIG" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)
cfg['setup_completado'] = False
cfg.pop('flask_secret', None)
with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=4)
print("      → config.json limpiado")
PYEOF
else
    echo "      → config.json no encontrado (omitido)"
fi

# ── [3] Claves SSH autorizadas del usuario ───────────────────────────
echo "[3/6] Borrando authorized_keys de storymaker..."
AUTH_KEYS="${ROOTFS}/home/storymaker/.ssh/authorized_keys"
[ -f "$AUTH_KEYS" ] && truncate -s 0 "$AUTH_KEYS" || true
echo "      → Hecho"

# ── [4] Claves SSH host del sistema ─────────────────────────────────
echo "[4/6] Eliminando claves SSH host..."
rm -f "${ROOTFS}"/etc/ssh/ssh_host_*
# Habilitar el servicio de regeneración creando el symlink de systemd
WANTS_DIR="${ROOTFS}/etc/systemd/system/multi-user.target.wants"
mkdir -p "$WANTS_DIR"
ln -sf /lib/systemd/system/regenerate_ssh_host_keys.service \
    "${WANTS_DIR}/regenerate_ssh_host_keys.service" 2>/dev/null || true
echo "      → Hecho"

# ── [5] Logs del sistema ──────────────────────────────────────────────
echo "[5/6] Limpiando logs..."
# Journal binario
find "${ROOTFS}/var/log/journal" -type f -name "*.journal" -delete 2>/dev/null || true
# Logs de texto
for LOG in auth.log syslog daemon.log kern.log user.log messages; do
    F="${ROOTFS}/var/log/${LOG}"
    [ -f "$F" ] && truncate -s 0 "$F" || true
done
echo "      → Hecho"

# ── [6] Bash history ─────────────────────────────────────────────────
echo "[6/6] Limpiando bash history..."
for HIST in "${ROOTFS}/home/storymaker/.bash_history" "${ROOTFS}/root/.bash_history"; do
    [ -f "$HIST" ] && truncate -s 0 "$HIST" || true
done
echo "      → Hecho"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  FS limpio. Listo para captura de imagen.            ║"
echo "╚══════════════════════════════════════════════════════╝"
