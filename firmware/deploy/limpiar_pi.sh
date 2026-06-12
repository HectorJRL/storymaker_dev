#!/usr/bin/env bash
# =============================================================================
# limpiar_pi.sh — Prepara la Pi para captura de imagen distributable
# =============================================================================
# Elimina todo dato personal/específico de la instalación:
#   • Perfiles WiFi de cliente (conserva el AP StoryMaker-Setup)
#   • flask_secret y setup_completado en config.json
#   • Claves SSH autorizadas del usuario storymaker
#   • Claves SSH host del sistema (se regeneran en el siguiente arranque)
#   • Logs del sistema y bash history
#
# USO — desde el ordenador de desarrollo:
#   ssh storymaker@<ip> 'bash -s' < firmware/deploy/limpiar_pi.sh
#
# O directamente en la Pi:
#   sudo bash limpiar_pi.sh
# =============================================================================

set -euo pipefail

echo "╔══════════════════════════════════════════════════════╗"
echo "║  StoryMaker — Limpieza para imagen distributable     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── [1] Perfiles WiFi de cliente ─────────────────────────────────────
echo "[1/6] Borrando perfiles WiFi de cliente..."

# Obtener conexiones WiFi en modo infrastructure (no AP)
while IFS= read -r CONN; do
    MODE=$(nmcli -t -f 802-11-wireless.mode connection show "$CONN" 2>/dev/null \
           | grep '802-11-wireless.mode' | cut -d: -f2 || echo "")
    if [ "$MODE" != "ap" ]; then
        echo "      Borrando: $CONN"
        sudo nmcli connection delete "$CONN" 2>/dev/null || true
    fi
done < <(nmcli -t -f NAME,TYPE connection show \
         | grep ':802-11-wireless$' \
         | cut -d: -f1)

echo "      → Hecho"

# ── [2] Limpiar config.json ──────────────────────────────────────────
echo "[2/6] Limpiando config.json..."

CONFIG="/home/storymaker/proyecto/data/config.json"
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
> /home/storymaker/.ssh/authorized_keys 2>/dev/null \
    || sudo bash -c '> /home/storymaker/.ssh/authorized_keys'
echo "      → Hecho"

# ── [4] Claves SSH host del sistema ─────────────────────────────────
echo "[4/6] Eliminando claves SSH host (se regeneran en el próximo arranque)..."

# Asegurar que el servicio de regeneración está habilitado
if systemctl list-unit-files regenerate_ssh_host_keys.service &>/dev/null; then
    sudo systemctl enable regenerate_ssh_host_keys.service 2>/dev/null || true
fi

sudo rm -f /etc/ssh/ssh_host_*
echo "      → Hecho"

# ── [5] Logs del sistema ──────────────────────────────────────────────
echo "[5/6] Limpiando logs..."
sudo journalctl --vacuum-size=1K 2>/dev/null || true
for LOG in /var/log/auth.log /var/log/syslog /var/log/daemon.log \
           /var/log/kern.log /var/log/user.log; do
    [ -f "$LOG" ] && sudo truncate -s 0 "$LOG" || true
done
echo "      → Hecho"

# ── [6] Bash history ─────────────────────────────────────────────────
echo "[6/6] Limpiando bash history..."
for HIST in /home/storymaker/.bash_history /root/.bash_history; do
    sudo truncate -s 0 "$HIST" 2>/dev/null || true
done
history -c 2>/dev/null || true
echo "      → Hecho"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Pi limpia. Lista para captura de imagen.            ║"
echo "╚══════════════════════════════════════════════════════╝"
