#!/usr/bin/env bash
# storymaker-wifi.sh — Gestión WiFi rápida para StoryMaker
# Instalar en: /usr/local/bin/storymaker-wifi.sh
set -euo pipefail

AP_SSID="StoryMaker-Setup"
AP_IP="10.42.0.1"
LOG="logger -t storymaker-wifi"

$LOG "Iniciando gestión WiFi..."

# Esperar solo a que NetworkManager esté operativo (no a que conecte)
for i in $(seq 1 10); do
    if nmcli general status &>/dev/null; then break; fi
    sleep 1
done

# ── Rescate AP: botón (GPIO5, activo LOW) pulsado al arrancar → forzar AP ──
# Útil cuando la red del centro tiene client isolation y el portátil no alcanza la Pi.
# Se mantiene pulsado durante el encendido (~3s) para activar el rescate.
FORCE_AP=false
if python3 -c "
import sys
try:
    import RPi.GPIO as GPIO, time
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(5, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(0.3)
    count = sum(1 for _ in range(10) if GPIO.input(5) == GPIO.LOW)
    GPIO.cleanup()
    sys.exit(0 if count >= 7 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    FORCE_AP=true
    $LOG "Botón pulsado al arrancar — modo AP de rescate forzado"
fi

# Comprobar si hay redes guardadas distintas del AP propio
KNOWN=$(nmcli -t -f NAME connection show | grep -v "^StoryMaker-Setup$" | grep -v "^Wired" | grep -v "^lo$" || true)

if [ "$FORCE_AP" = "false" ] && [ -n "$KNOWN" ]; then
    $LOG "Hay redes guardadas, esperando conexión automática de NM..."
    for i in $(seq 1 10); do
        STATE=$(nmcli -t -f DEVICE,STATE device status 2>/dev/null | grep "^wlan0:" | cut -d: -f2 || true)
        if [ "$STATE" = "connected" ]; then
            IP=$(nmcli -t -f IP4.ADDRESS device show wlan0 2>/dev/null | cut -d: -f2 | cut -d/ -f1 | head -1 || true)
            $LOG "WiFi conectado. IP: ${IP:-desconocida}"
            # Detectar si hay internet real o captive portal corporativo
            CONN=$(nmcli -t -f CONNECTIVITY general status 2>/dev/null || true)
            if [ "$CONN" = "portal" ]; then
                $LOG "AVISO: red con captive portal corporativo — sin internet real"
            elif [ "$CONN" = "limited" ] || [ "$CONN" = "none" ]; then
                $LOG "AVISO: conectado pero sin internet ($CONN)"
            fi
            rm -f /run/storymaker-ap-mode
            exit 0
        fi
        sleep 2
    done
    $LOG "Redes guardadas no disponibles en este entorno."
else
    if [ "$FORCE_AP" = "true" ]; then
        $LOG "Omitiendo redes guardadas por rescate AP."
    else
        $LOG "No hay redes guardadas."
    fi
fi

# Sin conexión WiFi (o rescate forzado) — activar AP
$LOG "Activando AP: $AP_SSID"
nmcli connection up "$AP_SSID" ifname wlan0 2>/dev/null || {
    $LOG "Error levantando AP, reintentando..."
    sleep 2
    nmcli connection up "$AP_SSID" ifname wlan0 2>/dev/null || true
}

# Verificar que el AP quedó activo de verdad antes de marcar el flag
if nmcli -t -f NAME connection show --active 2>/dev/null | grep -q "^StoryMaker-Setup$"; then
    touch /run/storymaker-ap-mode
    $LOG "AP activo. IP: $AP_IP"
else
    rm -f /run/storymaker-ap-mode
    $LOG "ERROR CRITICO: AP no pudo activarse. La Pi queda sin red."
fi
