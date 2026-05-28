#!/usr/bin/env bash
# =============================================================================
# prepare_sd.sh — Configura la SD de Pi OS Lite Bookworm tras flashear
# =============================================================================
# Equivale a las opciones de personalización de Raspberry Pi Imager cuando
# se usa una imagen de Bookworm seleccionada como "otro sistema operativo".
#
# Escribe directamente en la SD (sin arrancar la Pi):
#   • Crea el usuario "storymaker" con tu contraseña
#   • Habilita SSH
#   • Configura el hostname "storymaker"
#   • Guarda la red WiFi de desarrollo en NetworkManager
#
# USO (requiere sudo para montar particiones):
#   sudo ./prepare_sd.sh /dev/sdX "NombreWiFi" "ContraseñaWiFi"
#   sudo ./prepare_sd.sh /dev/sdX "NombreWiFi" ""    # red abierta
#
# Para identificar el dispositivo de la SD:
#   lsblk -o NAME,SIZE,LABEL,MOUNTPOINT | grep -v loop
# =============================================================================

set -euo pipefail

SD_DEV="${1:-}"
WIFI_SSID="${2:-}"
WIFI_PASS="${3:-}"   # puede estar vacío si la red es abierta

# ── Validaciones ──────────────────────────────────────────────────────────────
if [ -z "$SD_DEV" ] || [ -z "$WIFI_SSID" ]; then
    echo "Uso: sudo $0 /dev/sdX \"NombreWiFi\" \"ContraseñaWiFi\""
    echo ""
    echo "Dispositivos detectados:"
    lsblk -o NAME,SIZE,LABEL,MOUNTPOINT | grep -v loop
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: este script necesita ejecutarse con sudo"
    exit 1
fi

# Determinar nombres de partición (sdX1/sdX2 o mmcblkXp1/mmcblkXp2)
if [[ "$SD_DEV" == *mmcblk* ]]; then
    BOOT_PART="${SD_DEV}p1"
    ROOT_PART="${SD_DEV}p2"
else
    BOOT_PART="${SD_DEV}1"
    ROOT_PART="${SD_DEV}2"
fi

# Verificar que el dispositivo existe y tiene las dos particiones
if [ ! -b "$SD_DEV" ]; then
    echo "ERROR: dispositivo no encontrado: $SD_DEV"
    exit 1
fi
if [ ! -b "$BOOT_PART" ] || [ ! -b "$ROOT_PART" ]; then
    echo "ERROR: no se encuentran las particiones ${BOOT_PART} y ${ROOT_PART}"
    echo "¿Se flasheó correctamente la imagen?"
    exit 1
fi

# Pedir contraseña del usuario storymaker
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     StoryMaker — Preparación de SD                  ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Dispositivo: %-39s║\n" "$SD_DEV"
printf "║  Boot:        %-39s║\n" "$BOOT_PART"
printf "║  Root:        %-39s║\n" "$ROOT_PART"
printf "║  WiFi:        %-39s║\n" "$WIFI_SSID"
printf "║  Contraseña:  %-39s║\n" "$([ -n "$WIFI_PASS" ] && echo "configurada" || echo "sin contraseña (red abierta)")"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

read -r -s -p "Contraseña para el usuario 'storymaker' en la Pi: " SM_PASS
echo ""
read -r -s -p "Repite la contraseña: " SM_PASS2
echo ""

if [ "$SM_PASS" != "$SM_PASS2" ]; then
    echo "ERROR: las contraseñas no coinciden"
    exit 1
fi

if [ -z "$SM_PASS" ]; then
    echo "ERROR: la contraseña no puede estar vacía"
    exit 1
fi

# Verificar que las particiones no estén montadas ya
for PART in "$BOOT_PART" "$ROOT_PART"; do
    if mountpoint -q "$(lsblk -o MOUNTPOINT -n "$PART" 2>/dev/null | head -1)" 2>/dev/null; then
        echo "AVISO: $PART parece estar montada. Desmontando..."
        umount "$PART" 2>/dev/null || true
    fi
done

# ── Montaje ───────────────────────────────────────────────────────────────────
BOOT_MNT=$(mktemp -d /tmp/sm_boot_XXXXXX)
ROOT_MNT=$(mktemp -d /tmp/sm_root_XXXXXX)

cleanup() {
    echo ""
    echo "Limpiando montajes..."
    umount "$BOOT_MNT" 2>/dev/null || true
    umount "$ROOT_MNT" 2>/dev/null || true
    rmdir "$BOOT_MNT" "$ROOT_MNT" 2>/dev/null || true
}
trap cleanup EXIT

mount "$BOOT_PART" "$BOOT_MNT"
mount "$ROOT_PART" "$ROOT_MNT"

echo ""
echo "SD montada. Escribiendo configuración..."
echo ""

# =============================================================================
# [1] Habilitar SSH
# =============================================================================
echo "[1/5] Habilitando SSH..."
touch "${BOOT_MNT}/ssh"
echo "      → Archivo 'ssh' creado en boot"

# =============================================================================
# [2] Crear usuario storymaker con contraseña hasheada
# =============================================================================
echo "[2/5] Configurando usuario 'storymaker'..."

# openssl passwd -6 genera hash SHA-512 compatible con /etc/shadow
HASH=$(echo "$SM_PASS" | openssl passwd -6 -stdin)
echo "storymaker:${HASH}" > "${BOOT_MNT}/userconf.txt"
echo "      → userconf.txt escrito en boot"

# =============================================================================
# [3] Hostname
# =============================================================================
echo "[3/5] Configurando hostname 'storymaker'..."
echo "storymaker" > "${ROOT_MNT}/etc/hostname"

# Actualizar /etc/hosts (reemplazar el hostname genérico de la imagen)
if grep -q "raspberrypi\|raspberry" "${ROOT_MNT}/etc/hosts" 2>/dev/null; then
    sed -i "s/raspberrypi/storymaker/g; s/raspberry/storymaker/g" \
        "${ROOT_MNT}/etc/hosts"
else
    # Si no hay hostname genérico, añadir entrada estándar
    grep -q "storymaker" "${ROOT_MNT}/etc/hosts" \
        || echo "127.0.1.1       storymaker" >> "${ROOT_MNT}/etc/hosts"
fi
echo "      → /etc/hostname y /etc/hosts actualizados"

# =============================================================================
# [4] WiFi — perfil NetworkManager en el rootfs
# =============================================================================
echo "[4/5] Configurando WiFi '$WIFI_SSID'..."

NM_DIR="${ROOT_MNT}/etc/NetworkManager/system-connections"
mkdir -p "$NM_DIR"

NM_FILE="${NM_DIR}/storymaker-wifi.nmconnection"
UUID=$(python3 -c "import uuid; print(uuid.uuid4())")

if [ -n "$WIFI_PASS" ]; then
    # Red con contraseña (WPA/WPA2)
    cat > "$NM_FILE" <<NMCONF
[connection]
id=storymaker-wifi
uuid=${UUID}
type=wifi
autoconnect=true
autoconnect-priority=10

[wifi]
mode=infrastructure
ssid=${WIFI_SSID}

[wifi-security]
auth-alg=open
key-mgmt=wpa-psk
psk=${WIFI_PASS}

[ipv4]
method=auto

[ipv6]
addr-gen-mode=default
method=auto
NMCONF
else
    # Red abierta (sin contraseña)
    cat > "$NM_FILE" <<NMCONF
[connection]
id=storymaker-wifi
uuid=${UUID}
type=wifi
autoconnect=true
autoconnect-priority=10

[wifi]
mode=infrastructure
ssid=${WIFI_SSID}

[ipv4]
method=auto

[ipv6]
addr-gen-mode=default
method=auto
NMCONF
fi

# NetworkManager requiere permisos estrictos o ignora el archivo
chmod 600 "$NM_FILE"
echo "      → Perfil NM escrito en /etc/NetworkManager/system-connections/"

# =============================================================================
# [5] Verificación de archivos escritos
# =============================================================================
echo "[5/5] Verificando..."

OK=0; FAIL=0
check_file() {
    if [ -f "$1" ]; then
        echo "    ✓ $2"; OK=$((OK+1))
    else
        echo "    ✗ $2  ← NO ENCONTRADO"; FAIL=$((FAIL+1))
    fi
}

check_file "${BOOT_MNT}/ssh"          "boot/ssh (SSH habilitado)"
check_file "${BOOT_MNT}/userconf.txt" "boot/userconf.txt (usuario storymaker)"
check_file "${ROOT_MNT}/etc/hostname" "rootfs/etc/hostname"
check_file "$NM_FILE"                 "rootfs/etc/NetworkManager/.../${WIFI_SSID} (WiFi)"

echo ""
echo "      → $OK archivos correctos, $FAIL fallos"

# cleanup() se llama automáticamente al salir (trap EXIT)
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  SD preparada correctamente.                        ║"
    echo "║                                                      ║"
    echo "║  Siguiente paso:                                    ║"
    echo "║    1. Extrae la SD de este ordenador                ║"
    echo "║    2. Insértala en la Pi Zero 2W                    ║"
    echo "║    3. Enciende la Pi y espera ~60s                  ║"
    echo "║    4. Desde firmware/deploy/:                       ║"
    printf "║       ./setup_sd.sh <ip-de-la-pi>%-20s║\n" " "
    echo "╚══════════════════════════════════════════════════════╝"
else
    echo "⚠ Hubo fallos. Revisa los mensajes anteriores."
    exit 1
fi
