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

# Comprobar si ya hay alguna conexión WiFi guardada que esté al alcance
# Esto es rápido: compara SSIDs guardados con el escaneo actual
KNOWN=$(nmcli -t -f NAME connection show | grep -v "^StoryMaker-Setup$" | grep -v "^Wired" | grep -v "^lo$" || true)

if [ -n "$KNOWN" ]; then
    $LOG "Hay redes guardadas, esperando conexión automática de NM..."
    # Dar tiempo a NM para conectar por sí solo (ya lo intenta en paralelo)
    for i in $(seq 1 10); do
        STATE=$(nmcli -t -f DEVICE,STATE device status 2>/dev/null | grep "^wlan0:" | cut -d: -f2)
        if [ "$STATE" = "connected" ]; then
            IP=$(nmcli -t -f IP4.ADDRESS device show wlan0 2>/dev/null | cut -d: -f2 | cut -d/ -f1 | head -1)
            $LOG "WiFi conectado. IP: ${IP:-desconocida}"
            rm -f /run/storymaker-ap-mode
            exit 0
        fi
        sleep 2
    done
    $LOG "Redes guardadas no disponibles en este entorno."
else
    $LOG "No hay redes guardadas."
fi

# Sin conexión WiFi — activar AP inmediatamente
$LOG "Activando AP: $AP_SSID"
nmcli connection up "$AP_SSID" ifname wlan0 2>/dev/null || {
    $LOG "Error levantando AP, reintentando..."
    sleep 2
    nmcli connection up "$AP_SSID" ifname wlan0 2>/dev/null || true
}

touch /run/storymaker-ap-mode
$LOG "AP activo. IP: $AP_IP"
