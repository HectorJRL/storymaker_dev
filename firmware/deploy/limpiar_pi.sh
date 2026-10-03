#!/usr/bin/env bash
# =============================================================================
# limpiar_pi.sh — Prepara la Pi para captura de imagen distributable
# =============================================================================
# Elimina todo dato personal/específico de la instalación:
#   • flask_secret, setup_completado y PIN en config.json
#   • Copias .txt.bak que deja el importador de premisas
#   • Claves SSH autorizadas del usuario storymaker
#   • Claves SSH host del sistema (se regeneran en el siguiente arranque)
#   • Logs del sistema y bash history
#   • Contraseña de `storymaker`, que vuelve a la de fábrica
#   • El NOPASSWD: ALL de Raspberry Pi OS (010_pi-nopasswd)
#   • Perfiles WiFi de cliente (conserva el AP StoryMaker-Setup)
#
# El último paso va detachado con systemd-run y termina apagando la Pi: borrar
# el perfil WiFi activo mata la sesión SSH, así que nada que dependa de ella
# puede ir después. Ver el comentario del paso [8].
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

# ── [1] Limpiar config.json ──────────────────────────────────────────
echo "[1/8] Limpiando config.json..."

CONFIG="/home/storymaker/proyecto/data/config.json"
if [ -f "$CONFIG" ]; then
    python3 - "$CONFIG" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    cfg = json.load(f)
cfg['setup_completado'] = False
cfg.pop('flask_secret', None)
cfg['pin'] = '1234'          # el asistente de primer arranque pedirá otro
with open(path, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=4)
print("      → config.json limpiado")
PYEOF
else
    echo "      → config.json no encontrado (omitido)"
fi

# Copias de seguridad que deja el importador de premisas del portal: no tienen
# por qué viajar en una imagen distribuible.
sudo find "/home/storymaker/proyecto/data/perfiles" -name '*.txt.bak' -delete 2>/dev/null || true

# ── [2] Claves SSH autorizadas del usuario ───────────────────────────
echo "[2/8] Borrando authorized_keys de storymaker..."
> /home/storymaker/.ssh/authorized_keys 2>/dev/null \
    || sudo bash -c '> /home/storymaker/.ssh/authorized_keys'
echo "      → Hecho"

# ── [3] Claves SSH host del sistema ─────────────────────────────────
echo "[3/8] Eliminando claves SSH host (se regeneran en el próximo arranque)..."

# Asegurar que el servicio de regeneración está habilitado
if systemctl list-unit-files regenerate_ssh_host_keys.service &>/dev/null; then
    sudo systemctl enable regenerate_ssh_host_keys.service 2>/dev/null || true
fi

sudo rm -f /etc/ssh/ssh_host_*
echo "      → Hecho"

# ── [4] Logs del sistema ──────────────────────────────────────────────
echo "[4/8] Limpiando logs..."
sudo journalctl --vacuum-size=1K 2>/dev/null || true
for LOG in /var/log/auth.log /var/log/syslog /var/log/daemon.log \
           /var/log/kern.log /var/log/user.log; do
    [ -f "$LOG" ] && sudo truncate -s 0 "$LOG" || true
done
echo "      → Hecho"

# ── [5] Bash history ─────────────────────────────────────────────────
echo "[5/8] Limpiando bash history..."
for HIST in /home/storymaker/.bash_history /root/.bash_history; do
    sudo truncate -s 0 "$HIST" 2>/dev/null || true
done
history -c 2>/dev/null || true
echo "      → Hecho"

# ── [6] Contraseña de fábrica ────────────────────────────────────────
echo "[6/8] Restableciendo la contraseña de fábrica..."
# La imagen sale con una contraseña conocida y documentada, y el asistente de
# primer arranque obliga a cambiarla: así cada dispositivo acaba con la suya y
# no comparten todos la credencial que viaja dentro de la imagen publicada.
echo 'storymaker:storymaker' | sudo chpasswd
echo "      → contraseña de storymaker restablecida"

# ── [7] Comprobar requisitos del recorte de privilegios ──────────────
echo "[7/8] Comprobando requisitos antes de recortar sudo..."
# GUARDA IMPRESCINDIBLE: sin el ayudante y su línea de sudoers, el asistente de
# primer arranque no podría fijar la contraseña. Como es obligatoria, el usuario
# no podría completar la configuración y el dispositivo quedaría inservible.
# Antes que publicar una imagen así, abortamos y no se toca nada más.
if [ ! -x /usr/local/bin/storymaker-setpass ]; then
    echo "      ✗ ABORTADO: falta /usr/local/bin/storymaker-setpass"
    echo "        Despliega con deploy.sh y repite la limpieza."
    exit 1
fi
if ! sudo grep -q storymaker-setpass /etc/sudoers.d/storymaker-shutdown; then
    echo "      ✗ ABORTADO: /etc/sudoers.d/storymaker-shutdown no permite el ayudante"
    echo "        Despliega con deploy.sh y repite la limpieza."
    exit 1
fi
echo "      → ayudante y sudoers en su sitio"

# ── [8] Perfiles WiFi, recorte de sudo y apagado ─────────────────────
echo "[8/8] Borrando perfiles WiFi, recortando sudo y apagando..."
#
# POR QUÉ ESTE PASO VA AL FINAL Y DETACHADO:
#   `nmcli connection delete` sobre el perfil WiFi activo tumba la interfaz, y
#   con ella la sesión SSH desde la que corre este script. Cuando el borrado
#   estaba en el paso 1, los pasos siguientes NO llegaban a ejecutarse al
#   invocarlo como lo hace crear_imagen.sh:
#       ssh "$PI" 'bash -s' < limpiar_pi.sh
#   La imagen salía entonces con claves de host, authorized_keys, logs e
#   historial dentro. Lanzarlo como unidad transitoria de systemd lo desacopla
#   de la sesión: sobrevive a la caída de la red y acaba apagando la Pi.
#
#   El recorte de sudoers va DENTRO de la unidad porque, una vez eliminado
#   010_pi-nopasswd, un `sudo systemd-run` ya pediría contraseña. Así todo lo
#   privilegiado ocurre en un único contexto de root.
#
#   Lo que queda por hacer después es sólo apagar, así que perder la red no
#   estorba. El `sudo shutdown` que crear_imagen.sh lanza a continuación falla
#   sin consecuencias (ya lleva `|| true`).
sudo systemd-run --collect --unit=storymaker-limpieza-final /bin/bash -c '
    rm -f /etc/sudoers.d/010_pi-nopasswd
    for CONN in $(nmcli -t -f NAME,TYPE connection show | grep ":802-11-wireless$" | cut -d: -f1); do
        MODE=$(nmcli -t -f 802-11-wireless.mode connection show "$CONN" 2>/dev/null | cut -d: -f2)
        [ "$MODE" = "ap" ] || nmcli connection delete "$CONN"
    done
    sync
    sleep 2
    shutdown -h now
' >/dev/null 2>&1
echo "      → lanzado en segundo plano; la Pi se apagará sola en unos segundos"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Limpieza hecha. La Pi se está apagando.             ║"
echo "║  Verifica la SD antes de capturar la imagen.          ║"
echo "╚══════════════════════════════════════════════════════╝"
